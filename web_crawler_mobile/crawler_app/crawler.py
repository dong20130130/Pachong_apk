"""爬虫调度：广度优先遍历页面，收集资源。"""
import time
from collections import deque
from typing import Callable, Optional, Set
from urllib.parse import urlparse

import requests

from .config import DEFAULT_UA
from .extractor import extract, ext_of, looks_like_html, is_video_platform
from .models import Resource

FetchLog = Callable[[str], None]


class Crawler:
    def __init__(self, log: Optional[FetchLog] = None,
                 on_resource: Optional[Callable[[Resource], None]] = None,
                 on_progress: Optional[Callable[[int, int], None]] = None):
        self._log = log or (lambda m: None)
        self._on_resource = on_resource or (lambda r: None)
        self._on_progress = on_progress or (lambda c, t: None)
        self._stop = False

    def stop(self):
        self._stop = True

    def _session(self, ignore_ssl: bool) -> requests.Session:
        s = requests.Session()
        s.headers.update({"User-Agent": DEFAULT_UA,
                          "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})
        s.verify = not ignore_ssl
        return s

    def crawl(self, start_url: str, max_depth: int = 1, max_pages: int = 50,
              enabled_kinds=("video", "audio", "text", "image"),
              same_domain: bool = True, delay: float = 0.5,
              ignore_ssl: bool = False, timeout: int = 15):
        self._stop = False
        session = self._session(ignore_ssl)
        visited: Set[str] = set()
        resource_urls: Set[str] = set()
        queue = deque([(start_url, 0)])
        pages_done = 0

        # 起始 URL 本身就是视频平台播放页：直接登记为可下载视频资源
        if is_video_platform(start_url):
            self._log(f"[视频平台] 识别到视频页，将用 yt-dlp 解析：{start_url}")
            if start_url not in resource_urls:
                resource_urls.add(start_url)
                self._on_resource(Resource(
                    kind="video", url=start_url, source=start_url,
                    title=start_url.rsplit("/", 1)[-1] or start_url))

        while queue and pages_done < max_pages and not self._stop:
            url, depth = queue.popleft()
            if url in visited:
                continue
            visited.add(url)

            self._log(f"[{pages_done + 1}/{max_pages}] 抓取：{url}")
            try:
                resp = session.get(url, timeout=timeout)
            except Exception as e:  # noqa: BLE001
                self._log(f"  [失败] 请求失败：{e}")
                continue
            if not resp.ok:
                self._log(f"  [失败] 状态码 {resp.status_code}")
                continue
            ct = resp.headers.get("Content-Type", "")

            # 直链媒体（非 HTML）：直接作为资源
            if not looks_like_html(ct):
                kind = self._kind_by_ext(url)
                if kind and kind in enabled_kinds:
                    size = int(resp.headers.get("Content-Length", 0) or 0)
                    r = Resource(kind=kind, url=url, source=url,
                                 title=url.rsplit("/", 1)[-1], size=size)
                    if url not in resource_urls:
                        resource_urls.add(url)
                        self._on_resource(r)
                pages_done += 1
                self._on_progress(pages_done, max_pages)
                time.sleep(delay)
                continue

            # HTML 页面
            try:
                resp.encoding = resp.apparent_encoding or resp.encoding
                html = resp.text
            except Exception:  # noqa: BLE001
                html = resp.text
            resources, links = extract(html, url, enabled_kinds, same_domain)
            for r in resources:
                if r.url and r.url not in resource_urls:
                    resource_urls.add(r.url)
                    self._on_resource(r)

            if depth < max_depth:
                for link in links:
                    if link not in visited:
                        queue.append((link, depth + 1))

            pages_done += 1
            self._on_progress(pages_done, max_pages)
            if delay:
                time.sleep(delay)

        if self._stop:
            self._log("[已停止] 已手动停止。")
        else:
            self._log(f"[完成] 爬取结束，共访问 {pages_done} 个页面，"
                      f"发现 {len(resource_urls)} 个资源。")

    @staticmethod
    def _kind_by_ext(url: str) -> Optional[str]:
        from .config import MEDIA_EXT
        ext = ext_of(url)
        for kind, exts in MEDIA_EXT.items():
            if ext in exts:
                return kind
        return None
