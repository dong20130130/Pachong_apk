"""全局配置与常量。"""
import os

APP_NAME = "通用网页爬虫"
VERSION = "1.0.0"

# 默认请求头，模拟浏览器，降低被拦截概率
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# 各类资源的文件扩展名（小写），用于从链接里识别媒体
MEDIA_EXT = {
    "video": [".mp4", ".webm", ".ogg", ".mov", ".m4v", ".mkv", ".avi",
              ".flv", ".wmv", ".m3u8", ".ts", ".m2ts"],
    "audio": [".mp3", ".wav", ".oga", ".ogg", ".m4a", ".aac", ".flac",
              ".wma", ".opus"],
    "image": [".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".ico"],
}

# 视为 HTML 页面的 Content-Type
HTML_CONTENT_TYPES = ("text/html", "application/xhtml+xml", "application/xml")

# 资源类型的中文标签（用于界面展示）
KIND_LABELS = {
    "video": "视频",
    "audio": "音频",
    "text": "文本",
    "image": "图片",
}

# 默认输出目录（当前工作目录下的 downloads）
DEFAULT_OUTPUT_DIR = os.path.join(os.getcwd(), "downloads")

# 常见视频平台的域名（含子域）关键字，用于识别「视频页」而非普通网页
VIDEO_PLATFORM_DOMAINS = [
    "youtube.com", "youtu.be", "youtube-nocookie.com",
    "bilibili.com", "b23.tv", "tv.bilibili.com",
    "vimeo.com", "dailymotion.com", "tiktok.com", "douyin.com",
    "twitter.com", "x.com", "facebook.com", "instagram.com",
    "twitch.tv", "v.qq.com", "weibo.com", "ixigua.com",
    "acfun.cn", "yixiu.com", "kuaishou.com",
]

# 普通网页 URL 中暗示「这是一个视频页」的关键字
VIDEO_PLATFORM_KEYWORDS = [
    "/watch", "/video/", "player", "embed", "/bv", "/av",
    "v_show", "/play/", "video_id",
]
