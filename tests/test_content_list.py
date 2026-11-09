from zhibiao.content_list import _join, blocks_from_content_list, blocks_from_markdown


def test_text_table_equation_blocks_with_pages():
    items = [
        {"type": "text", "text": "第一章 招标公告", "page_idx": 0, "text_level": 1},
        {
            "type": "table",
            "table_body": "<table><tr><td>1</td></tr></table>",
            "table_caption": ["表1 项目概况"],
            "page_idx": 1,
        },
        {"type": "equation", "text": "E=mc^2", "page_idx": 2},
    ]

    blocks = blocks_from_content_list(items, page_offset=10)

    assert len(blocks) == 3
    assert blocks[0].page == 11
    assert blocks[0].level == 1
    assert blocks[1].page == 12
    assert "表1 项目概况" in blocks[1].text
    assert blocks[2].page == 13
    assert blocks[2].type == "equation"
    assert "$$" in blocks[2].text


def test_image_unknown_and_malformed_items():
    items = [
        {"type": "image", "image_caption": ["图1 项目位置"], "page_idx": 0},
        {"type": "custom", "text": "自定义内容", "page_idx": 1},
        {"type": "text", "text": "   ", "page_idx": 1},
    ]

    blocks = blocks_from_content_list(items)

    assert len(blocks) == 2
    assert blocks[0].type == "image"
    assert "图1 项目位置" in blocks[0].text
    assert blocks[1].type == "custom"
    assert blocks[1].text == "自定义内容"
    assert blocks_from_content_list([]) == []
    assert blocks_from_content_list(None) == []  # type: ignore[arg-type]
    assert blocks_from_content_list(
        [None, 42, {"type": "text", "text": None}, {"type": "table"}]
    ) == []


def test_markdown_blocks_and_join():
    markdown = "# 第一章 招标公告\n\n第一段\n继续\n\n## 1.1 项目概况\n内容"
    blocks = blocks_from_markdown(markdown, page_start=5)

    assert [block.level for block in blocks if block.level] == [1, 2]
    assert all(block.page == 5 for block in blocks)
    assert any("第一段" in block.text for block in blocks)
    assert _join(" a ") == "a"
    assert _join(["a", " b "]) == "a b"
    assert _join(None) == ""
