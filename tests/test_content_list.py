from zhibiao.content_list import blocks_from_content_list


def test_text_and_table_blocks_get_global_pages():
    items = [
        {"type": "text", "text": "第一章 招标公告", "page_idx": 0, "text_level": 1},
        {
            "type": "table",
            "table_body": "<table><tr><td>1</td></tr></table>",
            "table_caption": ["表1 项目概况"],
            "page_idx": 1,
        },
        {"type": "image", "img_path": "images/a.jpg", "page_idx": 2},
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
