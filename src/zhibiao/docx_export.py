from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

PLACEHOLDER = "【待填写】"
_TOKEN_RE = re.compile(r"(\*\*.+?\*\*|【待填写】)")


def _add_runs(paragraph, text: str) -> None:
    for token in _TOKEN_RE.split(text):
        if not token:
            continue
        if token == PLACEHOLDER:
            run = paragraph.add_run(token)
            run.bold = True
            run.font.color.rgb = RGBColor(0xC0, 0x00, 0x00)
        elif token.startswith("**") and token.endswith("**") and len(token) > 4:
            run = paragraph.add_run(token[2:-2])
            run.bold = True
        else:
            paragraph.add_run(token)


def _set_east_asian_font(style, name: str) -> None:
    style.font.name = name
    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.get_or_add_rFonts()
    rfonts.set(qn("w:eastAsia"), name)


def _parse_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_separator(line: str) -> bool:
    cells = _parse_row(line)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def _add_table(document: Document, rows: list[list[str]]) -> None:
    if not rows:
        return
    columns = max(len(row) for row in rows)
    table = document.add_table(rows=len(rows), cols=columns)
    try:
        table.style = "Table Grid"
    except KeyError:
        pass
    for row_index, row in enumerate(rows):
        for column_index in range(columns):
            cell = table.cell(row_index, column_index)
            cell.text = ""
            paragraph = cell.paragraphs[0]
            _add_runs(paragraph, row[column_index] if column_index < len(row) else "")
            if row_index == 0:
                for run in paragraph.runs:
                    run.bold = True


def export_markdown_to_docx(markdown: str, output_path: Path, title: str = "") -> Path:
    """把项目使用的 Markdown 子集转换为 Word；【待填写】统一标红加粗。"""
    document = Document()
    _set_east_asian_font(document.styles["Normal"], "宋体")
    document.styles["Normal"].font.size = Pt(11)
    for style_name in ("Heading 1", "Heading 2", "Heading 3", "Heading 4"):
        try:
            _set_east_asian_font(document.styles[style_name], "黑体")
        except KeyError:
            pass

    lines = markdown.splitlines()
    index = 0
    heading_seen = False

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if not stripped:
            index += 1
            continue

        if stripped.startswith("|"):
            rows: list[list[str]] = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                candidate = lines[index].strip()
                if not _is_separator(candidate):
                    rows.append(_parse_row(candidate))
                index += 1
            _add_table(document, rows)
            continue

        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            heading_text = stripped[level:].strip()
            paragraph = document.add_heading(heading_text, level=min(level, 4))
            if level == 1 and heading_seen:
                paragraph.paragraph_format.page_break_before = True
            heading_seen = True
            index += 1
            continue

        if re.match(r"^\s*[-*]\s+", line):
            paragraph = document.add_paragraph(style="List Bullet")
            _add_runs(paragraph, re.sub(r"^\s*[-*]\s+", "", line))
            index += 1
            continue

        if re.match(r"^\s*\d+[.)]\s+", line):
            paragraph = document.add_paragraph(style="List Number")
            _add_runs(paragraph, re.sub(r"^\s*\d+[.)]\s+", "", line))
            index += 1
            continue

        if stripped.startswith(">"):
            paragraph = document.add_paragraph()
            run = paragraph.add_run(stripped.lstrip("> ").strip())
            run.italic = True
            run.font.color.rgb = RGBColor(0x59, 0x59, 0x59)
            index += 1
            continue

        paragraph = document.add_paragraph()
        _add_runs(paragraph, stripped)
        index += 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(output_path))
    return output_path
