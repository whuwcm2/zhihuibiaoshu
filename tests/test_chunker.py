from zhibiao.chunker import (
    _merge_small,
    chunk_blocks,
    html_table_to_text,
    split_long_text,
)
from zhibiao.models import Block, Chunk


def test_split_long_text_boundaries():
    text = "甲" * 250
    pieces = split_long_text(text, max_chars=100, overlap=20)

    assert len(pieces) >= 3
    assert all(len(piece) <= 100 for piece in pieces)
    assert pieces[0][-20:] == pieces[1][:20]

    assert split_long_text("短文本", max_chars=100, overlap=20) == ["短文本"]
    varied = "".join(chr(0x4E00 + index) for index in range(250))
    no_overlap = split_long_text(varied, max_chars=100, overlap=0)
    assert len(no_overlap) >= 3
    assert all(len(piece) <= 100 for piece in no_overlap)
    assert no_overlap[0][-10:] != no_overlap[1][:10]


def test_chunk_blocks_splits_at_major_headings():
    blocks = [
        Block("第一章 招标公告", page=1, type="heading", level=1),
        Block("正文" * 120, page=1),
        Block("第二章 投标人须知", page=5, type="heading", level=1),
        Block("正文" * 120, page=5),
    ]
    chunks = chunk_blocks(blocks, max_chars=300, overlap=20)

    assert len(chunks) >= 2
    assert any("第一章 招标公告" in chunk.text for chunk in chunks)
    assert any("第二章 投标人须知" in chunk.text for chunk in chunks)


def test_chunk_pages_are_tracked():
    blocks = [
        Block("第一章 招标公告", page=3, type="heading", level=1),
        Block("正文内容" * 20, page=3),
        Block("更多内容" * 20, page=4),
    ]
    chunks = chunk_blocks(blocks, max_chars=500, overlap=20)

    assert chunks[0].page_start == 3
    assert chunks[0].page_end >= 3


def test_continuation_chunks_get_heading_context():
    blocks = [
        Block("第一章 招标公告", page=1, type="heading", level=1),
        Block("正文" * 200, page=1),
    ]
    chunks = chunk_blocks(blocks, max_chars=200, overlap=20)

    assert len(chunks) > 1
    assert "【章节】第一章 招标公告" in chunks[1].text


def test_html_table_conversion_and_plain_text():
    html = (
        "<table><tr><td>条款号</td><td>内容</td></tr>"
        "<tr><td>1.1</td><td>投标保证金</td></tr></table>"
    )
    text = html_table_to_text(html)

    assert "<td>" not in text
    assert "条款号 | 内容" in text
    assert "1.1 | 投标保证金" in text
    assert html_table_to_text("普通文本") == "普通文本"


def test_small_chunks_merged_and_empty_text_dropped():
    chunks = [
        Chunk("甲" * 50, page_start=1, page_end=1),
        Chunk("小", page_start=2, page_end=2),
        Chunk("乙" * 50, page_start=3, page_end=3),
    ]
    merged = _merge_small(chunks, min_chars=40)

    assert len(merged) == 2
    assert "小" in merged[0].text
    assert merged[0].page_end == 2
    assert chunk_blocks([Block(" ", page=1)], max_chars=100) == []
