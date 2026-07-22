"""下载与保存模块。

- 文本：直接把已提取正文写盘。
- 直链媒体（mp4/mp3...）：用 requests 流式下载，支持进度回调。
- 视频托管页（YouTube/Bilibili 等）：交给 yt-dlp 解析并下载。
"""
import os
import re
import shutil
import subprocess
import time
from typing import Callable, Optional

import requests

from .config import DEFAULT_UA, MEDIA_EXT
from .models import Resource

ProgressCb = Callable[[int, int], None]   # downloaded, total
StatusCb = Callable[[str], None]


def get_ffmpeg() -> Optional[str]:
    """定位 ffmpeg 可执行文件。

    优先使用 imageio-ffmpeg 自带的二进制（纯 Python 包，免系统安装），
    其次回退到系统 PATH 里的 ffmpeg。找不到返回 None。
    """
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            return exe
    except Exception:  # noqa: BLE001
        pass
    return shutil.which("ffmpeg")


def detect_installed_browsers() -> list:
    """探测本机实际安装的浏览器（用于 Cookie 自动提取）。

    返回按优先级排序的浏览器 key 列表，可能为空。
    支持：chrome / edge / firefox。
    """
    found = []
    local = os.environ.get("LOCALAPPDATA", "")
    roaming = os.environ.get("APPDATA", "")
    # Chrome / Edge 看 User Data 目录；Firefox 看 Profiles 目录
    checks = {
        "chrome": os.path.join(local, "Google", "Chrome", "User Data"),
        "edge": os.path.join(local, "Microsoft", "Edge", "User Data"),
        "firefox": os.path.join(roaming, "Mozilla", "Firefox", "Profiles"),
    }
    for name, path in checks.items():
        if path and os.path.isdir(path):
            # Firefox 需至少有 1 个 profile 子目录才算可用
            if name == "firefox":
                has_profile = any(
                    os.path.isdir(os.path.join(path, d))
                    for d in os.listdir(path)
                    if d.endswith(".default") or d.endswith(".release")
                    or d.startswith(".")
                )
                if not has_profile:
                    continue
            found.append(name)
    # 优先级：Chrome > Edge > Firefox
    order = {"chrome": 0, "edge": 1, "firefox": 2}
    return sorted(found, key=lambda b: order.get(b, 9))


def _resolve_cookie_opt(cookiefile: Optional[str],
                        browser: Optional[str]) -> Optional[dict]:
    """把“cookie 文件 / 浏览器”解析成要传给 yt-dlp 的 opts 片段。

    - 返回 dict：可用的 cookie opts（{cookiefile=...} 或 {cookiesfrombrowser=(b,)}）
    - 返回 {}：不启用 cookie
    - 返回 None：用户请求了 cookie 但当前不可用（文件缺失 / 浏览器未装），
      调用方应跳过 cookie 阶段并明确告知用户
    """
    if cookiefile:
        if os.path.exists(cookiefile) and os.path.getsize(cookiefile) > 0:
            return {"cookiefile": cookiefile}
        return None
    if browser and browser != "不使用":
        if browser == "自动检测":
            installed = detect_installed_browsers()
            if not installed:
                return None
            return {"cookiesfrombrowser": (installed[0],)}
        installed = detect_installed_browsers()
        if browser in installed:
            return {"cookiesfrombrowser": (browser,)}
        return None
    return {}


def _cookie_error_hint(msg: str) -> Optional[str]:
    """将 yt-dlp 的具体 Cookie 错误翻译成可操作的中文提示。

    尤其是 Chrome 在运行时锁定 cookie 数据库（yt-dlp issue #7271）导致
    “Could not copy Chrome cookie database” 这类错误——这种用浏览器直连
    基本无解，最稳妥的是改用导出的 cookies.txt 文件。
    """
    m = (msg or "").lower()
    if "could not copy" in m and ("cookie" in m or "7271" in m):
        return ("[建议] 这是 Chrome 锁定了 cookie 数据库所致（yt-dlp issue #7271）："
                "Chrome 运行时其 cookie 文件被占用，yt-dlp 无法复制读取。两种解法："
                "① 完全退出 Chrome（含后台进程）后重试；"
                "② 改用「cookies.txt 文件」方式——用浏览器插件在 bilibili.com 导出 "
                "cookies.txt，然后在界面点「浏览」选它，最稳，且不受此问题影响。")
    if "cookie" in m:
        return ("[建议] Cookie 读取失败。最稳妥的方式是改用「cookies.txt 文件」："
                "用浏览器插件（如 Get cookies.txt LOCALLY）在 bilibili.com 页面导出 "
                "cookies.txt，再到界面点「浏览」选它即可。")
    return None



class _YTLogger:
    """把 yt-dlp 的日志转发到界面，避免错误被 quiet 吞掉。"""

    def __init__(self, status: StatusCb):
        self._status = status

    def debug(self, msg: str):
        return  # 忽略噪声

    def info(self, msg: str):
        if msg:
            self._status(f"[yt-dlp] {msg}")

    def warning(self, msg: str):
        if msg:
            self._status(f"[yt-dlp警告] {msg}")

    def error(self, msg: str):
        if msg:
            self._status(f"[yt-dlp错误] {msg}")


def _probe_video_codec(path: str) -> Optional[str]:
    """用 ffmpeg -i 探测视频流编码（无 ffprobe 时退而用 ffmpeg）。"""
    ffmpeg = get_ffmpeg()
    if not ffmpeg or not os.path.exists(path):
        return None
    try:
        proc = subprocess.run([ffmpeg, "-i", path],
                              capture_output=True, text=True, timeout=30)
        out = proc.stderr
        m = re.search(r"Stream\s+#\d+:\d+.*?Video:\s*([a-zA-Z0-9_]+)", out)
        return m.group(1) if m else None
    except Exception:  # noqa: BLE001
        return None


def _warn_if_incompatible_codec(path: str, status: StatusCb):
    """若视频编码不是 H.264/avc（如 AV1/HEVC），很多播放器会黑屏只有声音，给出提醒。"""
    codec = _probe_video_codec(path)
    if not codec:
        return
    if codec.lower().startswith(("avc", "h264")):
        return
    status(f"[提醒] 视频编码为 {codec}，部分播放器（尤其老旧/浏览器内置）"
           f"可能无法解码而黑屏只有声音。建议用 VLC 播放，"
           f"或在 downloader 中开启“转码为 H.264”后重试。")


def _recent_valid_file(out_dir: str, window: float = 60.0) -> Optional[str]:
    """返回最近 window 秒内、体积 > 0 的文件路径（用于校验是否真的下到了东西）。"""
    now = time.time()
    best = None
    for root, _, files in os.walk(out_dir):
        for f in files:
            p = os.path.join(root, f)
            try:
                st = os.stat(p)
            except OSError:
                continue
            if st.st_size > 0 and (now - st.st_mtime) <= window:
                if best is None or st.st_mtime > best[1]:
                    best = (p, st.st_mtime)
    return best[0] if best else None


def _safe_filename(name: str, fallback: str, ext: str) -> str:
    name = (name or fallback or "resource").strip()
    name = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", name)
    name = name[:120]
    if ext and not name.lower().endswith(ext.lower()):
        name += ext
    return name


def save_text(res: Resource, out_dir: str, status: StatusCb) -> Optional[str]:
    os.makedirs(out_dir, exist_ok=True)
    base = res.title or res.url.rsplit("/", 1)[-1] or "page"
    fname = _safe_filename(base, "page", ".txt")
    path = os.path.join(out_dir, "text", fname)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # 避免覆盖：同名追加序号
    path = _uniq_path(path)
    with open(path, "w", encoding="utf-8") as f:
        if res.title:
            f.write(f"# {res.title}\n\n")
        if res.url:
            f.write(f"来源：{res.url}\n\n")
        f.write(res.text or "")
    status(f"已保存文本：{os.path.basename(path)}")
    return path


def _uniq_path(path: str) -> str:
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    i = 1
    while os.path.exists(f"{base}({i}){ext}"):
        i += 1
    return f"{base}({i}){ext}"


def _direct_download(url: str, out_path: str, progress: ProgressCb,
                     status: StatusCb, ignore_ssl: bool):
    headers = {"User-Agent": DEFAULT_UA,
               "Referer": url}
    with requests.get(url, headers=headers, stream=True,
                      timeout=30, verify=not ignore_ssl) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length", 0) or 0)
        done = 0
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 64):
                if not chunk:
                    continue
                f.write(chunk)
                done += len(chunk)
                progress(done, total)
        status(f"已下载：{os.path.basename(out_path)} "
               f"({done // 1024} KB)")

    return out_path


def _diagnose_formats(url: str, status: StatusCb, cookie_opt: dict):
    """所有策略失败后，探测 B站返回了多少格式，辅助判断是否为登录/地区限制。"""
    import yt_dlp
    try:
        opts = {
            "quiet": True,
            "no_warnings": True,
            "http_headers": {"User-Agent": DEFAULT_UA},
            "ignoreerrors": True,
        }
        if cookie_opt:
            opts.update(cookie_opt)
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        fmts = info.get("formats") or []
        status(f"[诊断] 该视频返回 {len(fmts)} 个格式。"
               + ("若为 0 或极少，通常是需要登录/地区限制："
                  "最稳妥的做法是用浏览器插件在 bilibili.com 导出 cookies.txt，"
                  "再到界面「浏览」选它重试（不受 Chrome 数据库锁问题影响）；"
                  "或确保已在对应浏览器登录 B站后选择「自动检测/对应浏览器」Cookie。"
                  if len(fmts) < 2 else
                  "格式列表正常，但仍失败可能是合并/网络问题，可重试。"))
    except Exception as e:  # noqa: BLE001
        status(f"[诊断] 无法获取格式列表：{e}")


def _ytdlp_download(url: str, out_dir: str, progress: ProgressCb,
                    status: StatusCb, cookiefile: Optional[str] = None,
                    browser: Optional[str] = None) -> str:
    import yt_dlp

    try:
        status(f"[yt-dlp] 版本 {yt_dlp.version.__version__}")
    except Exception:  # noqa: BLE001
        pass

    def hook(d):
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes", 0)
            progress(downloaded, total)
        elif d.get("status") == "finished":
            status(f"已下载：{os.path.basename(str(d.get('filename', '')))}")

    os.makedirs(os.path.join(out_dir, "video"), exist_ok=True)
    ffmpeg = get_ffmpeg()
    base_opts = {
        "outtmpl": os.path.join(out_dir, "video", "%(title)s.%(ext)s"),
        "progress_hooks": [hook],
        "logger": _YTLogger(status),
        "quiet": True,
        "no_warnings": False,
        "noplaylist": True,
        "http_headers": {"User-Agent": DEFAULT_UA},
        "ignoreerrors": False,   # 让真实错误抛出，便于定位
    }
    if ffmpeg:
        base_opts["ffmpeg_location"] = ffmpeg
    else:
        status("[警告] 未找到 ffmpeg，音视频可能无法合并（结果为空或失败）。"
               "请在输出目录检查，或安装 ffmpeg。")

    # 解析 Cookie 来源（浏览器自动探测 / cookie 文件）
    cookie_opt = _resolve_cookie_opt(cookiefile, browser)
    if cookie_opt is None:
        status("[提示] 已要求使用 Cookie，但找不到可用的浏览器或 cookie 文件，"
               "已跳过 Cookie 阶段。如需登录态下载，请在界面选择“自动检测”并确保已登录，"
               "或用浏览器插件导出 cookies.txt 后指定路径。")
        cookie_opt = {}
    elif cookie_opt:
        src = cookie_opt.get("cookiefile") or (
            "浏览器:" + cookie_opt["cookiesfrombrowser"][0])
        status(f"[Cookie] 本次使用：{src}")

    def build_opts(fmt, ck):
        opts = dict(base_opts)
        if fmt:
            opts["format"] = fmt
        if ck:
            opts.update(ck)
        return opts

    # 首选 H.264(avc1) 视频流，避免 AV1/HEVC 黑屏只有声音
    primary = "bestvideo[vcodec^=avc]+bestaudio/bestvideo+bestaudio/best"
    formats = [primary, "best", "best[ext=mp4]/best[ext=flv]/best", "worst"]

    # 阶段：先用 Cookie 试（若可用），失败再用无 Cookie 兜底
    if cookie_opt:
        phase_pairs = [(formats, cookie_opt), (formats, {})]
    else:
        phase_pairs = [(formats, {})]

    last_err: Optional[Exception] = None
    for fmts, ck in phase_pairs:
        tag = "（使用Cookie）" if ck else ""
        for i, fmt in enumerate(fmts):
            opts = build_opts(fmt, ck)
            try:
                status(f"[yt-dlp] 尝试格式策略 {i+1}/{len(fmts)}："
                       f"{fmt or '(默认)'}{tag}")
                with yt_dlp.YoutubeDL(opts) as ydl:
                    ydl.download([url])
                f = _recent_valid_file(out_dir)
                if f:
                    status(f"[yt-dlp] 下载成功（格式策略：{fmt or '(默认)'}{tag}）")
                    _warn_if_incompatible_codec(f, status)
                    return f
                # 未报错但也没生成有效文件：继续尝试下一种
                last_err = RuntimeError("yt-dlp 未生成有效文件")
                status(f"[yt-dlp] 格式策略 {fmt or '(默认)'}{tag} 未产出文件，尝试下一种。")
            except Exception as e:  # noqa: BLE001
                msg = str(e)
                is_fmt_err = ("Requested format is not available" in msg
                              or "format" in msg.lower())
                is_cookie_err = "cookie" in msg.lower()
                # 仅“格式不可用”或 Cookie 读取失败才继续尝试；
                # 网络/登录等硬错误直接抛出，不再无意义重试。
                if is_fmt_err or is_cookie_err:
                    if is_fmt_err:
                        last_err = e  # 记录真正的格式错误，便于最终提示
                        status(f"[yt-dlp] 格式 '{fmt or '(默认)'}' 不可用，"
                               f"自动尝试下一种策略。")
                    else:
                        status(f"[yt-dlp] Cookie 读取失败，跳过该策略："
                               f"{msg.splitlines()[0] if msg else ''}")
                        hint = _cookie_error_hint(msg)
                        if hint:
                            status(hint)
                    continue
                status(f"[失败] yt-dlp 下载失败：{msg}")
                raise

    # 所有阶段都失败：诊断并抛出
    _diagnose_formats(url, status, cookie_opt)
    raise last_err or RuntimeError("yt-dlp 所有格式策略均失败")


def download(res: Resource, out_dir: str, progress: ProgressCb,
             status: StatusCb, ignore_ssl: bool = False,
             cookiefile: Optional[str] = None,
             browser: Optional[str] = None) -> Optional[str]:
    """根据资源类型选择下载方式，返回保存路径或 None。

    cookiefile: 浏览器导出的 cookies.txt 路径（Netscape 格式），用于需要登录的站点。
    browser:    要提取 Cookie 的浏览器，如 "chrome"/"edge"/"firefox"/"自动检测"/"不使用"。
    """
    os.makedirs(out_dir, exist_ok=True)

    if res.kind == "text":
        return save_text(res, out_dir, status)

    url = res.url
    if not url:
        status("[失败] 资源缺少下载地址")
        return None

    ext = _ext_of_url(url)
    is_media_ext = any(ext in exts for exts in MEDIA_EXT.values())
    # HLS 直播/点播清单：直接下载只会拿到文本清单，必须交给 yt-dlp 合成
    is_hls = ext in (".m3u8", ".m3u")

    kind_dir = {"video": "video", "audio": "audio", "image": "image"}.get(
        res.kind, "other")
    out_sub = os.path.join(out_dir, kind_dir)
    os.makedirs(out_sub, exist_ok=True)

    # 视频托管页 / HLS 清单：优先用 yt-dlp 解析下载（不要回退到直链，否则只会抓到 HTML/清单）
    if res.kind in ("video", "audio") and (not is_media_ext or is_hls):
        try:
            status(f"尝试用 yt-dlp 解析：{url}")
            return _ytdlp_download(url, out_dir, progress, status,
                                   cookiefile=cookiefile, browser=browser)
        except Exception as e:  # noqa: BLE001
            status(f"[失败] yt-dlp 下载失败：{e}")
            return None

    # 直链媒体：直接下
    if is_media_ext and not is_hls:
        fname = _safe_filename(res.title or "", "media", ext or "")
        out_path = _uniq_path(os.path.join(out_sub, fname))
        try:
            return _direct_download(url, out_path, progress, status, ignore_ssl)
        except Exception as e:  # noqa: BLE001
            status(f"[失败] 直链下载失败：{e}")

    # 再兜底：当普通文件流下载
    try:
        fname = _safe_filename(res.title or "", "media", ext or "")
        out_path = _uniq_path(os.path.join(out_sub, fname))
        return _direct_download(url, out_path, progress, status, ignore_ssl)
    except Exception as e:  # noqa: BLE001
        status(f"[失败] 下载失败：{e}")
        return None


def _ext_of_url(url: str) -> str:
    from .extractor import ext_of
    return ext_of(url)
