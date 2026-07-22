# 打包 Android APK（手机端安装包）

本目录在原有 **桌面版（Tkinter）** 之外，新增了一套 **移动端（Kivy）** 实现。
两套界面共用同一份核心逻辑（`crawler_app/crawler.py`、`downloader.py`、
`extractor.py`、`models.py`、`config.py`），互不影响：

| 文件 | 用途 | 平台 |
|------|------|------|
| `main.py` / `gui.py` | 桌面版（Tkinter） | Windows / Linux / macOS |
| `main_android.py` / `gui_kivy.py` | 手机版（Kivy） | Android |
| `buildozer.spec` | 打包配置 | Android |
| `.github/workflows/build-apk.yml` | 云端一键编译 | GitHub Actions |

> 桌面版完全保留，未被改动。复制原文件夹用 `start.bat` 仍可正常打开。

---

## 方式一：GitHub Actions 云端编译（最省事，推荐）

无需在本机安装 Android SDK / Java / Buildozer，把仓库推到 GitHub 后由云端自动编译并产出 APK。

1. 把整个 `web_crawler_app` 文件夹作为 **Git 仓库根目录** 推到 GitHub
   （确保 `buildozer.spec`、`.github/workflows/build-apk.yml` 在仓库内）。
2. 打开仓库的 **Actions** 标签页 → 选择 `Build Android APK` → **Run workflow**。
   或只要有 `push` 到 `main`/`master`，也会自动触发。
3. 构建完成后，在 workflow 运行记录的 **Artifacts** 里下载 `webcrawler-apk`
   （一个 `bin/*.apk` 文件）。
4. 把 APK 传到手机，允许「未知来源」安装即可使用。

> 首次构建需下载 Android SDK/NDK（约 1~2 GB），通常 10~20 分钟；后续有缓存会更快。

---

## 方式二：本地 Ubuntu / WSL 编译

适合不想用 GitHub 的情况。需要一台 Linux 环境（WSL2 / 云主机均可，Windows 直接装会踩很多坑）。

```bash
# 1. 安装系统依赖
sudo apt update
sudo apt install -y git zip unzip openjdk-17-jdk python3-pip \
  autoconf automake libtool pkg-config

# 2. 安装 Buildozer
pip install --upgrade pip
pip install buildozer cython

# 3. 进入项目目录（即 buildozer.spec 所在目录）
cd web_crawler_app

# 4. 编译 debug 版 APK（首次会自动下载 SDK/NDK，请耐心等待）
buildozer android debug

# 5. 产物在 bin/ 目录下
ls bin/*.apk
```

---

## 已知限制（重要）

1. **视频平台下载（B站/YouTube 等）在手机端受限**
   核心逻辑复用桌面版，但 `yt-dlp` 合成音视频需要 **ffmpeg** 二进制。
   桌面端用 `imageio-ffmpeg` 自带的二进制；而 Android 是 ARM 架构、且 `imageio-ffmpeg`
   不含对应二进制，所以：
   - **文字、图片、音频直链**下载：正常。
   - **视频托管页（需 yt-dlp 合并）**：在手机端大概率只能拿到分立的音频/视频流，
     或合并失败。若要完整支持，需要为 python-for-android 单独提供 ARM 版 ffmpeg
     （超出本工程默认范围）。
2. **输出目录位置**
   默认下载到应用私有目录：`Android/data/org.example.webcrawler/files/downloads`。
   用文件管理器（如 MT 管理器）进入该路径即可找到文件。若想改成手机 `Download`
   目录，可在 `gui_kivy.py` 的 `_default_out_dir()` 中改用
   `android.storage.primary_external_storage_path()`，并确认已申请存储权限。
3. **Cookie 登录下载**
   手机端同样支持「cookies.txt」方式（界面点「选择 cookies.txt」）。
   浏览器自动探测（Chrome/Edge/Firefox）在 Android 上不可用，请用导出文件方式。

---

## 文件清单

- `crawler_app/gui_kivy.py` — Kivy 版界面（复用核心逻辑）
- `main_android.py` — Android 入口
- `buildozer.spec` — 打包配置（依赖、权限、SDK 版本）
- `.github/workflows/build-apk.yml` — 云端一键编译工作流
- 本文件 — 编译与使用说明
