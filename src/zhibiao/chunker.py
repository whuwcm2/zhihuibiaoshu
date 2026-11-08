from __future__ import annotations

import re
from html import unescape

from .models import Block, Chunk

_BOUNDARIES = "。！？；!?;\n"


def html_table_to_text(html: str) -> str:
    """把 MinerU 输出的 HTML 表格转成可读的管道分隔文本，减少 embedding 噪声。"""
    lowered = html.lower()
    if "<table" not in lowered and "</td>" not in lowered and "</th>" not in lowered:
        return html
    text = re.sub(r"(?i)</t[dh]\s*>", " | ", html)
    text = re.sub(r"(?i)</tr\s*>", "\n", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)

    lines: list[str] = []
    for line in text.splitlines():
        line = re.sub(r"\s*\|\s*$", "", line)
        line = re.sub(r"[ \t]+", " ", line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def split_long_text(text: str, max_chars: int, overlap: int) -> list[str]:
    """按句末标点/换行优先切分超长文本，并保留相邻片段的重叠。"""
    if max_chars <= 0 or len(text) <= max_chars:
        return [text.strip()] if text.strip() else []

    overlap = max(0, min(overlap, max_chars // 2))
    pieces: list[str] = []
    start = 0
    length = len(text)

    while start < length:
        end = min(start + max_chars, length)
        if end < length:
            window = text[start:end]
            best = max(window.rfind(char) for char in _BOUNDARIES)
            if best >= max_chars // 2:
                end = start + best + 1
        piece = text[start:end].strip()
        if piece:
            pieces.append(piece)
        if end >= length:
            break
        start = max(end - overlap, start + 1)

    return pieces


class _SectionChunker:
    def __init__(self, max_chars: int, overlap: int, split_level: int, min_chars: int) -> None:
        self.max_chars = max_chars
        self.overlap = overlap
        self.split_level = split_level
        self.min_chars = min_chars
        self.headings: list[tuple[int, str]] = []
        self.buffer: list[Block] = []
        self.chunks: list[Chunk] = []

    def add(self, block: Block) -> None:
        if block.type == "table":
            cleaned = html_table_to_text(block.text)
            if cleaned != block.text:
                block = Block(text=cleaned, page=block.page, type=block.type, level=block.level)

        if block.level > 0:
            if block.level <= self.split_level and self.buffer:
                self.flush()
            self._update_headings(block)

        if len(block.text) > self.max_chars:
            self.flush()
            for piece in split_long_text(block.text, self.max_chars, self.overlap):
                self.chunks.append(
                    self._make_chunk(
                        [Block(text=piece, page=block.page, type=block.type, level=block.level)]
                    )
                )
            return

        buffer_len = sum(len(item.text) + 2 for item in self.buffer)
        if self.buffer and buffer_len + len(block.text) + 2 > self.max_chars:
            self.flush()
        self.buffer.append(block)

    def flush(self) -> None:
        if not self.buffer:
            return
        buffered, self.buffer = self.buffer, []
        text = "\n\n".join(item.text.strip() for item in buffered if item.text.strip()).strip()
        if not text or len(re.sub(r"\s+", "", text)) < 10:
            return
        self.chunks.append(self._make_chunk(buffered, text=text))

    def _update_headings(self, block: Block) -> None:
        while self.headings and self.headings[-1][0] >= block.level:
            self.headings.pop()
        self.headings.append((block.level, block.text.strip()))

    def _heading_path(self) -> str:
        return " > ".join(title for _, title in self.headings if title)

    def _make_chunk(self, blocks: list[Block], text: str | None = None) -> Chunk:
        body = text if text is not None else "\n\n".join(
            item.text.strip() for item in blocks if item.text.strip()
        )
        heading = self._heading_path()
        starts_with_heading = bool(blocks and blocks[0].level > 0)
        if heading and not starts_with_heading:
            body = f"【章节】{heading}\n\n{body}"

        pages = [item.page for item in blocks]
        return Chunk(
            text=body.strip(),
            page_start=min(pages),
            page_end=max(pages),
            heading=heading,
            block_types=",".join(sorted({item.type for item in blocks})),
        )


def _merge_small(chunks: list[Chunk], min_chars: int) -> list[Chunk]:
    merged: list[Chunk] = []
    for chunk in chunks:
        if merged and len(chunk.text) < min_chars:
            previous = merged[-1]
            previous.text = f"{previous.text}\n\n{chunk.text}".strip()
            previous.page_end = max(previous.page_end, chunk.page_end)
            continue
        merged.append(chunk)
    return merged


def chunk_blocks(
    blocks: list[Block],
    max_chars: int = 1000,
    overlap: int = 120,
    split_level: int = 2,
    min_chars: int = 40,
) -> list[Chunk]:
    """把带页码的 Markdown 块按章节和长度切成检索片段。"""
    chunker = _SectionChunker(max_chars, overlap, split_level, min_chars)
    for block in blocks:
        chunker.add(block)
    chunker.flush()
    return _merge_small(chunker.chunks, min_chars)
