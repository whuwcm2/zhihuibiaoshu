from __future__ import annotations

from docx import Document

from zhibiao.docx_export import export_markdown_to_docx


def test_export_markdown_to_docx_with_table_and_placeholder(tmp_path):
    markdown = (
        "# 投标文件\n\n"
        "## 商务部分\n\n"
        "正文【待填写】和**加粗内容**。\n\n"
        "| 项目 | 内容 |\n"
        "|---|---|\n"
        "| 公司名称 | 【待填写】 |\n\n"
        "- 要点一\n"
    )
    path = export_markdown_to_docx(markdown, tmp_path / "bid.docx")

    document = Document(str(path))
    texts = [paragraph.text for paragraph in document.paragraphs]
    assert "投标文件" in texts
    assert any("正文【待填写】" in text for text in texts)
    assert len(document.tables) == 1
    assert document.tables[0].cell(1, 1).text == "【待填写】"

    placeholder_run = next(
        run
        for paragraph in document.paragraphs
        for run in paragraph.runs
        if "【待填写】" in run.text
    )
    assert placeholder_run.bold is True
    assert str(placeholder_run.font.color.rgb) == "C00000"
