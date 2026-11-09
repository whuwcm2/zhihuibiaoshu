from zhibiao.toc import parse_toc, toc_from_blocks


def test_parse_toc_levels_for_chapter_section_items():
    text = "\n".join([
        "第一章 招标公告.... 1",
        "第一节 项目概况.... 2",
        "一、投标函及投标函附录.... 3",
        "（一）投标函.... 4",
    ])

    entries = parse_toc(text)

    assert [(entry.title, entry.printed_page, entry.level) for entry in entries] == [
        ("第一章 招标公告", 1, 1),
        ("第一节 项目概况", 2, 2),
        ("一、投标函及投标函附录", 3, 2),
        ("（一）投标函", 4, 3),
    ]


def test_parse_toc_skips_non_toc_and_blank_lines():
    text = "\n".join([
        "这是普通正文，没有目录点线",
        "第1章 不是中文编号也没有页码",
        "[PDF p.6]",
        "第八章 投标文件格式…… 173",
    ])

    entries = parse_toc(text)

    assert len(entries) == 1
    assert entries[0].title == "第八章 投标文件格式"
    assert entries[0].printed_page == 173
    assert parse_toc("") == []
    assert parse_toc("\n\n   \n") == []
    assert parse_toc(".... 12") == []


def test_toc_from_blocks_filters_pages():
    blocks = [
        {"page": 6, "text": "第一章 招标公告.... 1\n第二章 投标人须知.... 7"},
        {"page": 20, "text": "第九章 不应进入目录.... 999"},
    ]

    entries = toc_from_blocks(blocks, start_page=1, end_page=10)

    assert [entry.title for entry in entries] == ["第一章 招标公告", "第二章 投标人须知"]
