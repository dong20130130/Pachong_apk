"""爬虫数据模型。"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Resource:
    """一个被发现的、可下载/保存的资源。"""
    kind: str            # video / audio / text / image
    url: str             # 资源地址（文本类型时也可为空）
    source: str = ""     # 发现该资源的页面 URL
    title: str = ""      # 展示用标题
    text: Optional[str] = None   # 文本类型的正文内容
    size: int = 0        # 字节数（已知时填入，如 Content-Length）
    # GUI 内部状态（非爬虫逻辑所需）
    selected: bool = field(default=False, repr=False)

    def display_name(self) -> str:
        if self.title:
            return self.title
        if self.url:
            return self.url.rsplit("/", 1)[-1] or self.url
        return f"{self.kind}-资源"
