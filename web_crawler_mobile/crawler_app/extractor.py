"""HTML 解析：从页面中提取媒体链接、正文文本与可继续爬取的链接。"""
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .config import MEDIA_EXT, HTML_CONTENT_TYPES, VIDEO_PLATFORM_DOMAINS, VIDEO_PLATFORM_KEYWORDS
from .models import Resource


def is_video_platform(url: str) -> bool:
    """判断一个 URL 是否指向视频平台（YouTube/Bilibili 等）。

    这类站点的视频由 JS/HLS 动态加载，静态 HTML 里没有可用直链，
    需要交给 yt-dlp 直接解析播放页 URL。
    """
    if not url:
        return False
    low = url.lower()
    from urllib.parse import urlparse
    netloc = urlparse(url).netloc.lower()
    if any(d in netloc for d in VIDEO_PLATFORM_DOMAINS):
        return True
    if any(k in low for k in VIDEO_PLATFORM_KEYWORDS):
        return True
    return False


def _ext(url: str) -> str:
    path = url.split("?", 1)[0].split("#", 1)[0]
    return "." + path.rsplit(".", 1)[-1].lower() if "." in path.rsplit("/", 1)[-1] else ""


def _same_netloc(a: str, b: str) -> bool:
    return urlparse(a).netloc == urlparse(b).netloc


def _clean_text(soup: BeautifulSoup) -> str:
    """尽量提取可读正文文本。"""
    for tag in soup(["script", "style", "noscript", "template", "svg", "head"]):
        tag.decompose()
    lines = []
    for elem in soup.stripped_strings:
        line = elem.strip()
        if line:
            lines.append(line)
    # 用空行分段落
    text = "\n".join(lines)
    # 压缩多余空行
    import re
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract(html: str, base_url: str, enabled_kinds, same_domain: bool = True):
    """解析一个 HTML 页面。

    返回 (resources, links)：
      - resources: 本页发现的 Resource 列表（视频/音频/图片/文本）
      - links: 本页中可继续爬取的同源 http(s) 链接集合
    """
    soup = BeautifulSoup(html, "lxml")
    resources: list[Resource] = []
    seen_urls: set[str] = set()

    def add(kind, url, title=""):
        if not url:
            return
        abs_url = urljoin(base_url, url)
        if abs_url in seen_urls:
            return
        if kind not in enabled_kinds:
            return
        seen_urls.add(abs_url)
        resources.append(Resource(kind=kind, url=abs_url, source=base_url,
                                 title=title or ""))

    # ---- 视频 / 音频：<video>、<audio>、<source> ----
    for tag in soup.find_all(["video", "audio", "source"]):
        src = tag.get("src")
        if src:
            kind = "audio" if tag.name == "audio" else (
                "video" if tag.name == "video" else None)
            if kind is None:
                # <source>：依据 type 或扩展名判断
                mtype = (tag.get("type") or "").lower()
                ext = _ext(src)
                if "video" in mtype or ext in MEDIA_EXT["video"]:
                    kind = "video"
                elif "audio" in mtype or ext in MEDIA_EXT["audio"]:
                    kind = "audio"
                else:
                    continue
            add(kind, src)
        # <video>/<audio> 上可能用 data-* 或子 <source>
        if tag.name in ("video", "audio"):
            for child in tag.find_all("source"):
                add(kind, child.get("src"))

    # ---- 图片 ----
    if "image" in enabled_kinds:
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src") or img.get("data-original")
            add("image", src, img.get("alt"))

    # ---- 嵌入的视频页（iframe / embed），交给 yt-dlp 处理 ----
    if "video" in enabled_kinds:
        for emb in soup.find_all(["iframe", "embed", "object"]):
            src = emb.get("src") or emb.get("data-src")
            if src and is_video_platform(src):
                add("video", src)

    # ---- 正文文本资源 ----
    if "text" in enabled_kinds:
        text = _clean_text(soup)
        title = soup.title.string.strip() if soup.title and soup.title.string else base_url
        res = Resource(kind="text", url=base_url, source=base_url,
                       title=title, text=text)
        resources.append(res)

    # ---- 可继续爬取的链接 ----
    links: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        abs_url = urljoin(base_url, href)
        p = urlparse(abs_url)
        if p.scheme not in ("http", "https"):
            continue
        # 指向视频平台的链接：直接登记为可下载的视频资源（交给 yt-dlp）
        if "video" in enabled_kinds and is_video_platform(abs_url):
            add("video", abs_url, a.get("title") or a.get_text(strip=True))
            continue
        if same_domain and not _same_netloc(abs_url, base_url):
            continue
        links.add(abs_url)

    return resources, links


def looks_like_html(content_type: str) -> bool:
    ct = (content_type or "").lower()
    return any(t in ct for t in HTML_CONTENT_TYPES) or ct == ""


def ext_of(url: str) -> str:
    return _ext(url)
