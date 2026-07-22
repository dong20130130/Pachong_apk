[app]

# 应用基本信息
title = 通用网页爬虫
package.name = webcrawler
package.domain = org.example.webcrawler
version = 1.0.0

# 入口：Kivy 版 GUI
android.entrypoint = main_android.py
main.py = main_android.py

# 源码目录（整个项目根）。排除虚拟环境与缓存，避免打包体积爆炸。
source.dir = .
source.include_exts = py,png,jpg,kv,txt,json,md
source.exclude_dirs = venv, .git, __pycache__, .workbuddy, bin, .buildozer
source.exclude_patterns = *.pyc, *.pyo, venv/*, *.spec, .idea/*, .vscode/*

# 依赖。注意：imageio-ffmpeg 自带的二进制是桌面版(x86/win)，
# 在 Android(ARM) 上无法使用，故不纳入；视频托管页的合并在手机端会受限
# （详见 BUILD_ANDROID.md）。文字/图片/音频直链下载不受影响。
requirements = python3,kivy,requests,beautifulsoup4,lxml,yt-dlp

# 屏幕与方向
orientation = portrait
fullscreen = 0
android.wakelock = True

# Android 权限
android.permissions = INTERNET, WRITE_EXTERNAL_STORAGE, READ_EXTERNAL_STORAGE, POST_NOTIFICATIONS
android.api = 33
android.minapi = 21
android.ndk = 25b
android.sdk = 33
android.accept_sdk_license = True
p4a.branch = master

[buildozer]
log_level = 2
warn_on_root = 0
