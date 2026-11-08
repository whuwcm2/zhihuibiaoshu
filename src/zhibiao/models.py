from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Block:
    """Markdown 化后的一个内容块，page 为 1-based 全局页码。"""

    text: str
    page: int
    type: str = "text"
    level: int = 0  # >0 表示标题层级，0 表示正文


@dataclass
class Chunk:
    text: str
    page_start: int
    page_end: int
    heading: str = ""
    block_types: str = ""
