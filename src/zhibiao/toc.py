from __future__ import annotations

import re
from dataclasses import dataclass

_TOC_LINE = re.compile(
    r"^(?P<title>.*?\S)\s*(?:[.·…]{2,})\s*(?P<page>\d+)\s*$"
)
_CHAPTER = re.compile(r"^第[一二三四五六七八九十百零〇]+章")
_SECTION = re.compile(r"^第[一二三四五六七八九十百零〇]+节")
_CN_ITEM = re.compile(r"^[一二三四五六七八九十百零〇]+、")
_PAREN_ITEM = re.compile(r"^[（(][一二三四五六七八九十百零〇]+[）)]")


@dataclass(frozen=True)
class TocEntry:
    title: str
    printed_page: int
    level: int


def _infer_level(title: str, leading_spaces: int) -> int:
    if _CHAPTER.match(title):
        return 1
    if _SECTION.match(title):
        return 2
    if _CN_ITEM.match(title):
        return 2
    if _PAREN_ITEM.match(title):
        return 3
    return 2 if leading_spaces >= 2 else 1


def parse_toc(text: str) -> list[TocEntry]:
    """解析带点线页码的目录行，例如“第八章 投标文件格式.... 173”。"""
    entries: list[TocEntry] = []
    for raw_line in text.splitlines():
        leading = len(raw_line) - len(raw_line.lstrip(" \t"))
        line = raw_line.strip()
        if not line or line.startswith("[PDF p."):
            continue
        match = _TOC_LINE.match(line)
        if not match:
            continue
        title = match.group("title").strip()
        if not title or set(title) <= set(".·… "):
            continue
        entries.append(
            TocEntry(
                title=title,
                printed_page=int(match.group("page")),
                level=_infer_level(title, leading),
            )
        )
    return entries


def toc_from_blocks(
    blocks: list[dict], start_page: int = 1, end_page: int = 10
) -> list[TocEntry]:
    """从解析缓存 blocks 的前几页中提取目录。"""
    text = "\n".join(
        str(block.get("text") or "")
        for block in blocks
        if start_page <= int(block.get("page") or 0) <= end_page
    )
    return parse_toc(text)
