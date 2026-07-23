[app]

# 应用基本信息
title = 通用网页爬虫
package.name = webcrawler
package.domain = org.example.webcrawler
version = 1.0.0

# 入口：Kivy 版 GUI。注意：buildozer 硬性要求入口文件名必须是 main.py，
# 且位于 source.dir 根目录；“main.py = xxx” 这种写法不会被识别。

# 源码目录（整个项目根）。排除虚拟环境与缓存，避免打包体积爆炸。
source.dir = .
source.include_exts = py,png,jpg,kv,txt,json,md,ttf,otf
# 中文字体目录（CJK TTF/OTF），见 crawler_app/gui_kivy.py 的 _register_cjk_font。
# 该目录下的字体文件会被上面的 include_exts(ttf,otf) 一并打包进 APK。
source.exclude_dirs = venv, .git, __pycache__, .workbuddy, bin, .buildozer, keystore
source.exclude_patterns = *.pyc, *.pyo, venv/*, *.spec, .idea/*, .vscode/*

# 依赖。注意：imageio-ffmpeg 自带的二进制是桌面版(x86/win)，
# 在 Android(ARM) 上无法使用，故不纳入；视频托管页的合并在手机端会受限
# （详见 BUILD_ANDROID.md）。文字/图片/音频直链下载不受影响。
# 不依赖 lxml（改用 Python 内置 html.parser），减少 p4a 编译失败风险。
# python3 与 hostpython3 必须同版本：hostpython3 是 p4a 用来交叉编译其他配方的
# 宿主 Python，两者不一致会报 "python3 should have same version as hostpython3"。
# 必须锁完整版本号(带补丁)：只写 "3.11" 会让 p4a 拼出 .../3.11/Python-3.11.tar.xz 而 404。
requirements = python3==3.11.9,hostpython3==3.11.9,kivy,requests,beautifulsoup4,yt-dlp

# 屏幕与方向
orientation = portrait
fullscreen = 0
android.wakelock = True

# Android 权限
android.permissions = INTERNET, WRITE_EXTERNAL_STORAGE, READ_EXTERNAL_STORAGE, POST_NOTIFICATIONS
android.api = 33
android.minapi = 21
android.sdk = 33
android.accept_sdk_license = True
# 固定 NDK 为 25b：buildozer 1.5.0 自带的 python-for-android(2024.x) 与 NDK r28c 不兼容，
# 会导致 pythonforandroid.toolchain create 失败；25b 是该组合下经过验证的稳定版本。
android.ndk = 25b
# 只编 arm64-v8a：减少编译内存占用与耗时（armeabi-v7a 现代手机基本不需要），降低 OOM 失败概率。
android.archs = arm64-v8a

# 固定签名密钥（用于免卸载覆盖安装）：
# 不在此处配置 android.keystore —— buildozer `android debug` 会忽略它，
# 改用 ~/.android/debug.keystore 签名。CI 工作流把仓库内固定密钥库
# (keystore/debug.keystore，标准 Android debug 格式 alias=androiddebugkey/密码=android)
# 复制到 ~/.android/debug.keystore，使每次 debug 构建签名一致，手机可直接覆盖安装。
# 注意：这是 debug 用途的密钥，切勿用于正式发布；若仓库为公开仓库，等同公开签名。
# 不固定 p4a.branch：使用 buildozer 依赖锁定的 p4a 版本，避免主干漂移。

[buildozer]
log_level = 2
warn_on_root = 0
