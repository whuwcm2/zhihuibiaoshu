from __future__ import annotations

from .models import Block


def _join(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return " ".join(str(item).strip() for item in value if str(item).strip())
    return ""


def blocks_from_content_list(items: list[dict], page_offset: int = 0) -> list[Block]:
    """把 MinerU 的 content_list.json 转成带全局页码的 Markdown 块。

    page_offset 是本分片之前的总页数（0-based），用于把分片内 page_idx 换算成全局页码。
    """
    blocks: list[Block] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        page = int(item.get("page_idx", 0) or 0) + page_offset + 1
        item_type = str(item.get("type") or "text").lower()

        if item_type == "text":
            text = _join(item.get("text"))
            if not text:
                continue
            level = int(item.get("text_level") or 0)
            blocks.append(Block(text=text, page=page, type="text", level=level))

        elif item_type == "table":
            caption = _join(item.get("table_caption"))
            body = _join(item.get("table_body"))
            footnote = _join(item.get("table_footnote"))
            text = "\n\n".join(part for part in (caption, body, footnote) if part)
            if text:
                blocks.append(Block(text=text, page=page, type="table"))

        elif item_type == "image":
            caption = _join(item.get("image_caption") or item.get("img_caption"))
            footnote = _join(item.get("image_footnote") or item.get("img_footnote"))
            text = "\n\n".join(part for part in (caption, footnote) if part)
            if text:
                blocks.append(Block(text=text, page=page, type="image"))

        elif item_type == "equation":
            text = _join(item.get("text"))
            if text:
                blocks.append(Block(text=f"$$\n{text}\n$$", page=page, type="equation"))

        else:
            text = _join(item.get("text"))
            if text:
                blocks.append(Block(text=text, page=page, type=item_type))

    return blocks


def blocks_from_markdown(markdown: str, page_start: int) -> list[Block]:
    """content_list 缺失时的降级：按标题/空行把 Markdown 切成块（仅保留起始页）。"""
    blocks: list[Block] = []
    paragraph: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            text = "\n".join(paragraph).strip()
            if text:
                blocks.append(Block(text=text, page=page_start, type="text"))
            paragraph.clear()

    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped:
            flush_paragraph()
            continue
        if stripped.startswith("#"):
            flush_paragraph()
            level = len(stripped) - len(stripped.lstrip("#"))
            title = stripped[level:].strip()
            blocks.append(
                Block(text=title, page=page_start, type="heading", level=min(level, 6))
            )
            continue
        paragraph.append(line)

    flush_paragraph()
    return blocks
