from __future__ import annotations

from pathlib import Path

import pymupdf

from .models import Block


def parse_with_pymupdf(pdf_path: Path, out_dir: Path) -> tuple[Path, list[Block]]:
    """MinerU 不可用时的兜底解析：逐页提取文本并生成 Markdown。

    注意：如果 PDF 缺少 ToUnicode 映射（常见于扫描件/特殊字体），提取结果可能乱码。
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    blocks: list[Block] = []
    markdown_parts: list[str] = []
    total_chars = 0
    replacement_chars = 0

    with pymupdf.open(pdf_path) as doc:
        for page_index, page in enumerate(doc, start=1):
            text = page.get_text("text").strip()
            if not text:
                continue
            total_chars += len(text)
            replacement_chars += text.count("�")
            blocks.append(Block(text=f"第 {page_index} 页", page=page_index, type="heading", level=2))
            blocks.append(Block(text=text, page=page_index, type="text"))
            markdown_parts.append(f"## 第 {page_index} 页\n\n{text}")

    markdown_path = out_dir / "fallback.md"
    markdown_path.write_text("\n\n".join(markdown_parts), encoding="utf-8")
    if not total_chars:
        print("[warn] PyMuPDF 未提取到任何文本（可能是扫描件），需要 OCR/MinerU", flush=True)
    elif replacement_chars / total_chars > 0.02:
        print(
            f"[warn] PyMuPDF 提取文本中替换字符占 {replacement_chars / total_chars:.1%}，"
            "可能是字体编码问题，建议改用 MinerU",
            flush=True,
        )
    return markdown_path, blocks
