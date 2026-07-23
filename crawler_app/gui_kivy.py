"""移动端 GUI（Android）：用 Kivy 实现，完全复用 crawler_app 核心逻辑。

设计要点：
- 不 import 任何 Tkinter，UI 与核心逻辑解耦（与桌面版一致）。
- 耗时任务（爬取 / 下载）放在后台线程，通过 queue + Clock 回灌主线程刷新 UI。
- 同一套 Crawler / downloader / Resource 接口，桌面版与手机版共用一份逻辑。
"""
import os
import queue
import threading

from kivy.app import App
from kivy.clock import Clock
from kivy.metrics import dp, sp
from kivy.utils import platform
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox
from kivy.uix.spinner import Spinner
from kivy.uix.progressbar import ProgressBar
from kivy.uix.popup import Popup
from kivy.uix.filechooser import FileChooserListView

from crawler_app.config import APP_NAME, VERSION, KIND_LABELS
from crawler_app.crawler import Crawler
from crawler_app.downloader import download
from crawler_app.models import Resource


# ---------------------------------------------------------------------------
# 中文字体：Kivy 默认 Roboto 不含中文字形，所有中文会显示成方框(□)。
# 这里把项目 fonts/ 下的 CJK 字体注册为 Kivy 默认别名 "Roboto"，并同时设为
# Kivy 全局默认字体(default_font)，确保所有未显式指定 font_name 的控件
# (Label/Button/TextInput/Spinner…)都用中文字体。
# 字体文件须由构建方提供(见下方候选名)，且 buildozer.spec 的
# source.include_exts 必须含 ttf，才会被打包进 APK。
# 加载结果写入 _CJK_FONT_MSG，App.build() 会把它打到日志面板，方便排查。
# ---------------------------------------------------------------------------
_CJK_FONT_MSG = "未加载中文字体（中文将显示为方框）"


def _register_cjk_font():
    import os as _os
    from kivy.core.text import LabelBase
    from kivy.config import Config
    global _CJK_FONT_MSG
    _here = _os.path.dirname(_os.path.abspath(__file__))
    _font_dir = _os.path.normpath(_os.path.join(_here, "..", "fonts"))
    _candidates = [
        "NotoSansSC-Regular.ttf",
        "simhei.ttf",
        "simkai.ttf",
        "Deng.ttf",
        "simfang.ttf",
    ]
    for _name in _candidates:
        _path = _os.path.join(_font_dir, _name)
        if _os.path.exists(_path):
            LabelBase.register(
                name="Roboto",
                fn_regular=_path,
                fn_bold=_path,
                fn_italic=_path,
                fn_bolditalic=_path,
            )
            # 同时设为全局默认字体，覆盖所有未指定 font_name 的控件
            # 注意：Kivy 的 default_font 是逗号分隔字符串，不能用列表
            Config.set("kivy", "default_font",
                       "Roboto,%s,%s,%s" % (_path, _path, _path))
            _CJK_FONT_MSG = "已加载中文字体：" + _name
            return
    _CJK_FONT_MSG = "未找到中文字体（目录 %s）" % _font_dir


_register_cjk_font()


# ---------------------------------------------------------------------------
# 单个资源行（含勾选框 + 类型 + 名称）
# ---------------------------------------------------------------------------
class ResRow(BoxLayout):
    def __init__(self, res: Resource, on_toggle, **kwargs):
        super().__init__(**kwargs)
        self.orientation = "horizontal"
        self.size_hint_y = None
        self.height = dp(34)
        self.spacing = dp(4)
        self.res = res

        cb = CheckBox(size_hint_x=None, width=dp(26), color=(1, 1, 1, 1))
        cb.bind(active=on_toggle)
        self.cb = cb
        self.add_widget(cb)

        kind = KIND_LABELS.get(res.kind, res.kind)
        self.add_widget(Label(text=kind, size_hint_x=None, width=dp(42),
                              font_size=sp(11), color=(0.9, 0.9, 0.9, 1)))

        name = res.display_name()
        if len(name) > 38:
            name = name[:38] + "..."
        self.add_widget(Label(text=name, size_hint_x=1, font_size=sp(11),
                              color=(1, 1, 1, 1)))


# ---------------------------------------------------------------------------
# 主应用
# ---------------------------------------------------------------------------
class CrawlerApp(App):
    title = f"{APP_NAME} v{VERSION}"

    # ---- 生命周期 ----
    def build(self):
        self.msg_queue = queue.Queue()
        self.resources = []
        self.crawler = None
        self.crawl_thread = None
        self.download_thread = None
        self._downloading = False
        self.cookiefile = ""
        self.out_dir = self._default_out_dir()

        root = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(6))

        # 标题
        root.add_widget(Label(text=f"{APP_NAME}  v{VERSION}",
                              size_hint_y=None, height=dp(26),
                              font_size=sp(15), bold=True, color=(1, 1, 1, 1)))

        # 网址行
        url_row = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(6))
        # 进入时网址栏为空；用 hint_text 提示用户输入（不再预填 example.com）
        self.url_input = TextInput(text="", hint_text="请输入网址", multiline=False,
                                   size_hint_x=0.55,
                                   background_color=(0.16, 0.16, 0.16, 1),
                                   foreground_color=(1, 1, 1, 1))
        self.btn_clear_url = Button(text="清空", size_hint_x=0.13,
                                    background_color=(0.3, 0.3, 0.3, 1))
        self.btn_start = Button(text="开始爬取", size_hint_x=0.25,
                                background_color=(0.05, 0.39, 0.61, 1))
        self.btn_stop = Button(text="停止", size_hint_x=0.12, disabled=True)
        url_row.add_widget(self.url_input)
        url_row.add_widget(self.btn_clear_url)
        url_row.add_widget(self.btn_start)
        url_row.add_widget(self.btn_stop)
        root.add_widget(url_row)

        # 视频平台直链行
        vp_row = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(6))
        self.vp_input = TextInput(hint_text="视频平台直链(B站/YouTube)",
                                  multiline=False, size_hint_x=0.7,
                                  background_color=(0.16, 0.16, 0.16, 1),
                                  foreground_color=(1, 1, 1, 1))
        self.btn_vp = Button(text="yt-dlp下载", size_hint_x=0.3)
        vp_row.add_widget(self.vp_input)
        vp_row.add_widget(self.btn_vp)
        root.add_widget(vp_row)

        # Cookie 行
        cookie_row = BoxLayout(size_hint_y=None, height=dp(38), spacing=dp(6))
        self.browser_spin = Spinner(text="自动检测",
                                    values=["自动检测", "不使用", "Chrome",
                                            "Edge", "Firefox"],
                                    size_hint_x=0.42,
                                    background_color=(0.25, 0.25, 0.25, 1))
        self.btn_cookie = Button(text="选择 cookies.txt", size_hint_x=0.42)
        self.cookie_label = Label(text="未选择", size_hint_x=0.16,
                                  font_size=sp(11), color=(0.8, 0.8, 0.8, 1))
        cookie_row.add_widget(self.browser_spin)
        cookie_row.add_widget(self.btn_cookie)
        cookie_row.add_widget(self.cookie_label)
        root.add_widget(cookie_row)

        # 提取类型行
        kind_row = BoxLayout(size_hint_y=None, height=dp(34), spacing=dp(8))
        kind_row.add_widget(Label(text="提取:", size_hint_x=None, width=dp(48),
                                  color=(1, 1, 1, 1), font_size=sp(12)))
        self.kind_cbs = {}
        for k in ("video", "audio", "text", "image"):
            cb = CheckBox(active=True, size_hint_x=None, width=dp(22))
            lab = Label(text=KIND_LABELS[k], size_hint_x=None, width=dp(46),
                        font_size=sp(12), color=(1, 1, 1, 1))
            self.kind_cbs[k] = cb
            kind_row.add_widget(cb)
            kind_row.add_widget(lab)
        root.add_widget(kind_row)

        # 选项行：深度 / 页数 / 同域 / 忽略SSL
        opt_row = BoxLayout(size_hint_y=None, height=dp(34), spacing=dp(6))
        opt_row.add_widget(Label(text="深度", size_hint_x=None, width=dp(36),
                                 color=(1, 1, 1, 1), font_size=sp(12)))
        self.depth_in = TextInput(text="1", multiline=False, input_filter="int",
                                  size_hint_x=None, width=dp(40),
                                  background_color=(0.16, 0.16, 0.16, 1),
                                  foreground_color=(1, 1, 1, 1))
        opt_row.add_widget(self.depth_in)
        opt_row.add_widget(Label(text="页数", size_hint_x=None, width=dp(36),
                                 color=(1, 1, 1, 1), font_size=sp(12)))
        self.pages_in = TextInput(text="50", multiline=False, input_filter="int",
                                  size_hint_x=None, width=dp(48),
                                  background_color=(0.16, 0.16, 0.16, 1),
                                  foreground_color=(1, 1, 1, 1))
        opt_row.add_widget(self.pages_in)
        self.same_cb = CheckBox(active=True, size_hint_x=None, width=dp(22))
        opt_row.add_widget(self.same_cb)
        opt_row.add_widget(Label(text="同域", size_hint_x=None, width=dp(40),
                                 color=(1, 1, 1, 1), font_size=sp(12)))
        self.ssl_cb = CheckBox(active=False, size_hint_x=None, width=dp(22))
        opt_row.add_widget(self.ssl_cb)
        opt_row.add_widget(Label(text="忽略SSL", size_hint_x=None, width=dp(56),
                                 color=(1, 1, 1, 1), font_size=sp(12)))
        root.add_widget(opt_row)

        # 中部：资源列表 + 日志（纵向各占一半）
        mid = BoxLayout(orientation="vertical", size_hint_y=1, spacing=dp(4))

        res_box = BoxLayout(orientation="vertical", size_hint_y=0.5)
        res_box.add_widget(Label(text="资源列表 (点击勾选)", size_hint_y=None,
                                 height=dp(22), font_size=sp(12),
                                 color=(0.8, 0.8, 0.8, 1)))
        self.res_layout = GridLayout(cols=1, size_hint_y=None, spacing=dp(2))
        self.res_layout.bind(minimum_height=self.res_layout.setter("height"))
        res_sv = ScrollView()
        res_sv.add_widget(self.res_layout)
        res_box.add_widget(res_sv)
        mid.add_widget(res_box)

        log_box = BoxLayout(orientation="vertical", size_hint_y=0.5)
        log_box.add_widget(Label(text="日志", size_hint_y=None, height=dp(22),
                                 font_size=sp(12), color=(0.8, 0.8, 0.8, 1)))
        self.log_label = Label(text="", size_hint_y=None, size_hint_x=1,
                               font_size=sp(11),
                               color=(0.85, 0.85, 0.85, 1),
                               halign="left", valign="top")
        self.log_label.bind(
            texture_size=lambda inst, sz: setattr(inst, "height", sz[1]))
        # 只允许纵向滚动，横向靠自动换行
        log_sv = ScrollView(do_scroll_x=False, do_scroll_y=True)
        log_sv.add_widget(self.log_label)
        # 把文本宽度约束到滚动视图宽度 → 长行自动换行，不再溢出显示不全
        log_sv.bind(width=lambda inst, w: setattr(
            self.log_label, "text_size", (w, None)))
        log_box.add_widget(log_sv)
        mid.add_widget(log_box)
        root.add_widget(mid)

        # 底部：操作 + 进度
        bottom = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(6))
        self.btn_selall = Button(text="全选", size_hint_x=0.13)
        self.btn_invert = Button(text="反选", size_hint_x=0.13)
        self.btn_dl = Button(text="下载选中", size_hint_x=0.22,
                             background_color=(0.05, 0.39, 0.61, 1))
        # 打开输出目录（手动查看已下载文件）
        self.btn_opendir = Button(text="打开目录", size_hint_x=0.17,
                                  background_color=(0.3, 0.3, 0.3, 1))
        # 下载完成后直接打开（勾选后，用系统查看器打开刚下载的文件/目录）
        self.open_after_cb = CheckBox(active=False, size_hint_x=0.08)
        self.open_after_lab = Label(text="下完打开", size_hint_x=0.12,
                                    font_size=sp(11), color=(0.85, 0.85, 0.85, 1))
        self.progress = ProgressBar(size_hint_x=0.15, max=100, value=0)
        bottom.add_widget(self.btn_selall)
        bottom.add_widget(self.btn_invert)
        bottom.add_widget(self.btn_dl)
        bottom.add_widget(self.btn_opendir)
        bottom.add_widget(self.open_after_cb)
        bottom.add_widget(self.open_after_lab)
        bottom.add_widget(self.progress)
        root.add_widget(bottom)

        self.status_label = Label(text="就绪", size_hint_y=None, height=dp(20),
                                  font_size=sp(11), color=(0.8, 0.8, 0.8, 1))
        root.add_widget(self.status_label)

        # 绑定事件
        self.btn_start.bind(on_release=self.start_crawl)
        self.btn_stop.bind(on_release=self.stop_crawl)
        self.btn_clear_url.bind(on_release=self.clear_url)
        self.btn_vp.bind(on_release=self.download_platform)
        self.btn_cookie.bind(on_release=self.open_filechooser)
        self.btn_selall.bind(on_release=self.select_all)
        self.btn_invert.bind(on_release=self.invert_sel)
        self.btn_dl.bind(on_release=self.start_download)
        self.btn_opendir.bind(on_release=self.open_out_dir)

        # 后台线程结果轮询（在主线程刷新 UI）
        Clock.schedule_interval(self._poll, 0.1)

        self._log(f"输出目录：{self.out_dir}")
        self._log("[提示] 即手机文件管理器中的『内部存储/pachong』")
        self._log(_CJK_FONT_MSG)
        if not self._ensure_manage_storage(jump=False):
            self._log("[提示] 下载需『所有文件访问权限』，首次下载会跳转到设置页开启")
        return root

    # ---- 默认输出目录 ----
    def _default_out_dir(self):
        # 下载到内部存储根目录下的 pachong 文件夹，用户在文件管理器自行创建。
        # 优先用 /sdcard：它是内部存储根的符号链接，文件管理器显示即『内部存储』，
        # 这样日志提示的路径（/sdcard/pachong）与用户在文件管理器看到的完全一致；
        # 拿不到再回退到 Environment 真实路径 / 外部文件目录 / 内部目录 / cwd。
        candidates = ["/sdcard"]
        try:
            from jnius import autoclass
            Environment = autoclass("android.os.Environment")
            p = Environment.getExternalStorageDirectory().getAbsolutePath()
            if p:
                candidates.insert(0, p)
        except Exception:
            pass
        for c in candidates:
            if c and os.path.isdir(c):
                return os.path.join(c, "pachong")
        # 兜底（非 Android / 极端情况）
        try:
            return os.path.join(App.get_running_app().user_data_dir, "pachong")
        except Exception:
            return os.path.join(os.getcwd(), "pachong")

    # ---- 日志 ----
    def _log(self, msg):
        lines = self.log_label.text.split("\n")
        lines.append(msg)
        if len(lines) > 400:
            lines = lines[-400:]
        self.log_label.text = "\n".join(lines)

    # ---- Cookie 参数 ----
    def _cookie_args(self):
        if self.cookiefile:
            return self.cookiefile, None
        return None, self.browser_spin.text

    # ---- 一键清空网址栏 ----
    def clear_url(self, *a):
        self.url_input.text = ""
        self.url_input.focus = True

    # ---- 选择 cookies.txt ----
    def open_filechooser(self, *a):
        chooser = FileChooserListView(filters=["*.txt"])
        popup = Popup(title="选择 cookies.txt", size_hint=(0.9, 0.9))

        def on_sel(instance, selection):
            if selection:
                self.cookiefile = selection[0]
                self.cookie_label.text = os.path.basename(selection[0])
            popup.dismiss()

        chooser.bind(on_selection=on_sel)
        box = BoxLayout(orientation="vertical")
        box.add_widget(chooser)
        btn = Button(text="取消", size_hint_y=None, height=dp(40))
        btn.bind(on_release=popup.dismiss)
        box.add_widget(btn)
        popup.content = box
        popup.open()

    # ---- 爬取 ----
    def start_crawl(self, *a):
        url = self.url_input.text.strip()
        if not url:
            self._log("请输入目标网址")
            return
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
            self.url_input.text = url
        enabled = tuple(k for k in ("video", "audio", "text", "image")
                        if self.kind_cbs[k].active)
        if not enabled:
            self._log("请至少选择一种提取类型")
            return

        self.resources.clear()
        self.res_layout.clear_widgets()
        self.log_label.text = ""
        self.btn_start.disabled = True
        self.btn_stop.disabled = False
        self.progress.value = 0

        crawler = Crawler(
            log=lambda m: self.msg_queue.put(("log", m)),
            on_resource=self._on_resource,
            on_progress=lambda c, t: self.msg_queue.put(
                ("crawl_progress", (c, t))),
        )
        self.crawler = crawler

        def run():
            try:
                crawler.crawl(
                    url,
                    max_depth=int(self.depth_in.text or 1),
                    max_pages=max(1, int(self.pages_in.text or 50)),
                    enabled_kinds=enabled,
                    same_domain=self.same_cb.active,
                    delay=0.5,
                    ignore_ssl=self.ssl_cb.active,
                )
            except Exception as e:  # noqa: BLE001
                self.msg_queue.put(("log", f"[异常] {e}"))
            self.msg_queue.put(("crawl_done", None))

        self.crawl_thread = threading.Thread(target=run, daemon=True)
        self.crawl_thread.start()

    def stop_crawl(self, *a):
        if self.crawler:
            self.crawler.stop()
        self._log("[停止] 正在停止...")

    def _on_resource(self, res):
        self.msg_queue.put(("resource", res))

    # ---- Android 11+ 存储权限（写 /sdcard 根目录必需）----
    def _ensure_manage_storage(self, jump=False):
        # MANAGE_EXTERNAL_STORAGE 是特殊权限：仅靠 buildozer.spec 声明不够，
        # 必须运行时引导用户到系统设置页手动开启，否则写入 /sdcard 根目录
        # 会报 "Operation not permitted"。
        try:
            from jnius import autoclass, cast
            Build = autoclass("android.os.Build")
            if Build.VERSION.SDK_INT < 30:
                return True  # Android 10 及以下用旧存储模型即可
            Environment = autoclass("android.os.Environment")
            if Environment.isExternalStorageManager():
                return True  # 已授权
            if jump:
                PythonActivity = autoclass("org.kivy.android.PythonActivity")
                context = cast("android.content.Context", PythonActivity.mActivity)
                Intent = autoclass("android.content.Intent")
                Settings = autoclass("android.provider.Settings")
                Uri = autoclass("android.net.Uri")
                intent = Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION)
                intent.setData(Uri.fromParts("package", context.getPackageName(), None))
                context.startActivity(intent)
                self._log("[权限] 已打开设置页，请开启『所有文件访问权限』后返回 App")
            return False
        except Exception as e:  # noqa: BLE001
            # 桌面或非 Android 环境无 jnius/Android 类，直接放行
            self._log(f"[权限] 检测跳过（非 Android）：{e}")
            return True

    # ---- 下载 ----
    def download_platform(self, *a):
        if self._downloading:
            self._log("正在下载中，请稍候")
            return
        url = self.vp_input.text.strip()
        if not url:
            self._log("请输入视频平台链接")
            return
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        if not self._ensure_manage_storage(jump=True):
            return
        os.makedirs(self.out_dir, exist_ok=True)
        self._downloading = True
        self.status_label.text = "yt-dlp 解析中..."
        self._log(f"[视频平台] 开始下载：{url}")
        res = Resource(kind="video", url=url, source=url,
                       title=url.rsplit("/", 1)[-1] or "video")

        def run():
            cf, br = self._cookie_args()
            paths = []
            try:
                p = download(res, self.out_dir,
                             progress=lambda c, t: self.msg_queue.put(
                                 ("download_progress", (c, t))),
                             status=lambda m: self.msg_queue.put(("log", m)),
                             ignore_ssl=self.ssl_cb.active,
                             cookiefile=cf, browser=br)
                if p:
                    paths.append(p)
            except Exception as e:  # noqa: BLE001
                self.msg_queue.put(("log", f"[失败] {e}"))
            self.msg_queue.put(("download_done", (1, paths)))

        threading.Thread(target=run, daemon=True).start()

    def start_download(self, *a):
        if self._downloading:
            self._log("正在下载中，请稍候")
            return
        selected = [r for r in self.resources if r.selected]
        if not selected:
            self._log("请先选择要下载的资源")
            return
        if not self._ensure_manage_storage(jump=True):
            return
        os.makedirs(self.out_dir, exist_ok=True)
        self._downloading = True
        self.btn_start.disabled = True

        def run():
            total = len(selected)
            cf, br = self._cookie_args()
            paths = []
            for i, res in enumerate(selected, 1):
                self.msg_queue.put(("download_file", (i, total, res)))
                try:
                    p = download(res, self.out_dir,
                                 progress=lambda c, t: self.msg_queue.put(
                                     ("download_progress", (c, t))),
                                 status=lambda m: self.msg_queue.put(("log", m)),
                                 ignore_ssl=self.ssl_cb.active,
                                 cookiefile=cf, browser=br)
                    if p:
                        paths.append(p)
                except Exception as e:  # noqa: BLE001
                    self.msg_queue.put(
                        ("log", f"[失败] {res.display_name()}: {e}"))
            self.msg_queue.put(("download_done", (total, paths)))

        self.download_thread = threading.Thread(target=run, daemon=True)
        self.download_thread.start()

    # ---- 下载完成后直接打开（安卓：调起系统查看器打开文件/目录） ----
    def _open_downloaded(self, paths):
        try:
            from jnius import autoclass
            import mimetypes
            Intent = autoclass("android.content.Intent")
            Uri = autoclass("android.net.Uri")
            File = autoclass("java.io.File")
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            activity = PythonActivity.mActivity
            if len(paths) == 1:
                target = paths[0]
                mime = mimetypes.guess_type(target)[0] or "*/*"
            else:
                target, mime = self.out_dir, "*/*"
            uri = Uri.fromFile(File(target))
            intent = Intent(Intent.ACTION_VIEW)
            intent.setDataAndType(uri, mime)
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            activity.startActivity(intent)
            self._log(f"[打开] 已请求系统打开：{target}")
        except Exception as e:  # noqa: BLE001
            self._log(f"[打开失败] {e}（可改用『打开目录』手动查看）")

    # ---- 打开输出目录（手动查看已下载文件）----
    def open_out_dir(self, *a):
        os.makedirs(self.out_dir, exist_ok=True)
        # 无论能否唤起文件管理器，都把完整路径显著打到日志，保证手动可找到
        self._log(f"[目录] 下载保存在：{self.out_dir}")
        try:
            from jnius import autoclass
            Intent = autoclass("android.content.Intent")
            Uri = autoclass("android.net.Uri")
            File = autoclass("java.io.File")
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            activity = PythonActivity.mActivity
            uri = Uri.fromFile(File(self.out_dir))
            intent = Intent(Intent.ACTION_VIEW)
            # 部分文件管理器识别该 MIME 打开文件夹
            intent.setDataAndType(uri, "resource/folder")
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            activity.startActivity(intent)
            self._log("[目录] 已请求打开文件夹（若无反应，请用手机文件管理器按上面路径查找）")
        except Exception as e:  # noqa: BLE001
            self._log(f"[提示] 无法唤起文件管理器：{e}")
            self._log("请打开手机『文件管理』App，按上面显示的路径手动查看。")

    # ---- 资源列表选择 ----
    def select_all(self, *a):
        for r in self.resources:
            r.selected = True
        self._refresh_checks()

    def invert_sel(self, *a):
        for r in self.resources:
            r.selected = not r.selected
        self._refresh_checks()

    def _refresh_checks(self):
        for child in self.res_layout.children:
            if isinstance(child, ResRow):
                child.cb.active = child.res.selected

    # ---- 消息队列处理（主线程） ----
    def _poll(self, dt):
        try:
            while True:
                kind, payload = self.msg_queue.get_nowait()
                self._handle(kind, payload)
        except queue.Empty:
            pass

    def _handle(self, kind, payload):
        if kind == "log":
            self._log(payload)
        elif kind == "resource":
            self._add_resource(payload)
        elif kind == "crawl_progress":
            cur, tot = payload
            self._set_progress(cur, tot)
            self.status_label.text = f"爬取中 {cur}/{tot}"
        elif kind == "crawl_done":
            self.btn_start.disabled = False
            self.btn_stop.disabled = True
            self.status_label.text = f"就绪（共 {len(self.resources)} 个资源）"
        elif kind == "download_file":
            i, tot, res = payload
            self.status_label.text = f"下载 {i}/{tot}: {res.display_name()}"
        elif kind == "download_progress":
            cur, tot = payload
            self._set_progress(cur, tot)
        elif kind == "download_done":
            self._downloading = False
            self.btn_start.disabled = False
            self._set_progress(0, 0)
            total, paths = payload
            self.status_label.text = f"下载完成，共 {total} 个"
            self._log(f"[完成] 下载结束，保存到：{self.out_dir}")
            if self.open_after_cb.active and paths:
                self._open_downloaded(paths)

    def _set_progress(self, cur, tot):
        if tot and tot > 0:
            self.progress.max = tot
            self.progress.value = min(cur, tot)
        else:
            self.progress.max = 100
            self.progress.value = (self.progress.value + 4) % 100

    def _add_resource(self, res: Resource):
        self.resources.append(res)

        def on_toggle(instance, value, r=res):
            r.selected = value

        row = ResRow(res, on_toggle)
        self.res_layout.add_widget(row)


def main():
    CrawlerApp().run()


if __name__ == "__main__":
    main()
