from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from zhibiao import extractor
from zhibiao.extractor import (
    DeepSeekExtractor,
    ExtractionError,
    _fill_missing_dates,
    _merge_items,
    _normalize_event,
    _parse_json_text,
    check_provenance,
    render_markdown,
    render_pages,
    split_context,
)
from zhibiao.pipeline import make_doc_id, sha1_file


class FakeMessage:
    def __init__(self, content):
        self.content = content


class FakeChoice:
    def __init__(self, content, finish_reason="stop"):
        self.message = FakeMessage(content)
        self.finish_reason = finish_reason


class FakeCompletionResponse:
    def __init__(self, content, finish_reason="stop"):
        self.choices = [FakeChoice(content, finish_reason)]


class FakeCompletions:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        item = self.responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class FakeOpenAI:
    def __init__(self, responses):
        self.chat = SimpleNamespace(completions=FakeCompletions(responses))


def make_extractor(settings, responses):
    extractor_instance = DeepSeekExtractor(settings)
    fake = FakeOpenAI(responses)
    extractor_instance.client = fake
    return extractor_instance, fake


def test_render_pages_skips_page_numbers_and_cleans_tables():
    blocks = [
        {"text": "正文内容", "page": 3, "type": "text"},
        {"text": "3", "page": 3, "type": "page_number"},
        {"text": "<table><tr><td>A</td><td>B</td></tr></table>", "page": 4, "type": "table"},
    ]

    context = render_pages(blocks, 3, 4)

    assert "[PDF p.3]" in context
    assert "正文内容" in context
    assert "[PDF p.4]" in context
    assert "<td>" not in context
    assert "A | B" in context


def test_split_context_keeps_page_marker():
    context = "[PDF p.14]\n" + "\n".join(f"row {i} " + "x" * 80 for i in range(20))

    parts = split_context(context, 300)

    assert len(parts) > 1
    assert all(part.startswith("[PDF p.14]") for part in parts)


def test_parse_json_text_variants():
    assert _parse_json_text('{"a": 1}') == {"a": 1}
    assert _parse_json_text('```json\n{"a": 1}\n```') == {"a": 1}
    assert _parse_json_text('前缀 {"a": 1} 后缀') == {"a": 1}
    with pytest.raises(json.JSONDecodeError):
        _parse_json_text("not json")


def test_merge_items_dedup_prefers_longer():
    items = [
        {"clause": "1.1", "item": "招标人", "content": "短"},
        {"clause": "1.1", "item": "招标人", "content": "更长的内容"},
        {"clause": "", "item": "", "content": "应丢弃"},
        {"clause": "2.1", "item": "其他", "content": "x"},
    ]

    merged = _merge_items(items, ("clause", "item"))

    assert len(merged) == 2
    assert next(item for item in merged if item["clause"] == "1.1")["content"] == "更长的内容"


def test_normalize_and_fill_dates():
    assert _normalize_event("开标时间") == "开标"
    assert _normalize_event("截止日期") == "截止"
    assert _normalize_event(None) == ""

    overview = {"fields": [{"name": "投标有效期", "value": "自投标截止日起90天", "page": 14}]}
    dates = [
        {"event": "开标", "datetime": "2023-11-14 13:30", "page": 12},
        {"event": "开标时间", "datetime": None, "page": 40},
    ]
    result = _fill_missing_dates(dates, overview)

    assert any(item["event"] == "投标有效期" for item in result)
    assert not any(item["event"] == "开标时间" for item in result)

    contained = _fill_missing_dates(
        [
            {"event": "开标时间", "datetime": "2023-11-14 13:30", "page": 12},
            {"event": "开标（同投标截止时间）", "datetime": None, "page": 40},
            {"event": "踏勘现场", "datetime": None, "page": 14},
        ],
        None,
    )
    assert not any(item["event"].startswith("开标（") for item in contained)
    assert any(item["event"] == "踏勘现场" for item in contained)


def test_deepseek_requires_api_key(settings):
    with pytest.raises(ExtractionError):
        DeepSeekExtractor(replace(settings, deepseek_api_key=""))


def test_deepseek_json_call_success_retry_and_fenced_json(settings):
    instance, fake = make_extractor(
        settings,
        [
            FakeCompletionResponse("not json"),
            FakeCompletionResponse('```json\n{"ok": true}\n```'),
        ],
    )

    assert instance.json_call("prompt") == {"ok": True}
    assert len(fake.chat.completions.calls) == 2
    assert fake.chat.completions.calls[0]["response_format"] == {"type": "json_object"}
    assert fake.chat.completions.calls[0]["model"] == "deepseek-flash"


def test_deepseek_truncation_and_missing_key(settings):
    instance, fake = make_extractor(
        settings,
        [FakeCompletionResponse('{"ok": 1}', finish_reason="length") for _ in range(3)],
    )
    with pytest.raises(ExtractionError, match="截断"):
        instance.json_call("prompt")
    assert len(fake.chat.completions.calls) == 3

    instance, _ = make_extractor(
        settings,
        [
            FakeCompletionResponse('{"wrong": {}}'),
            FakeCompletionResponse('{"evaluation": {"method": "综合评估法"}}'),
        ],
    )
    assert instance.extract_section("evaluation", "prompt") == {"method": "综合评估法"}

    instance, _ = make_extractor(
        settings,
        [FakeCompletionResponse('{"wrong": {}}'), FakeCompletionResponse('{"wrong": {}}')],
    )
    with pytest.raises(ExtractionError, match="evaluation"):
        instance.extract_section("evaluation", "prompt")


def test_render_markdown_includes_toc_and_validation_notes():
    result = {
        "source": "doc.pdf",
        "doc_id": "d",
        "generated_at": "now",
        "toc": [{"title": "第一章 招标公告", "printed_page": 1, "level": 1}],
        "project_overview": {"fields": [{"name": "项目名称", "value": "X", "page": 1}]},
        "evaluation": {
            "method": "综合评估法",
            "total_points": 100,
            "points_breakdown": [{"item": "施工组织设计评审", "points": 30, "page": 1}],
            "preliminary_review": [
                {"category": "形式评审", "item": "名称", "standard": "s", "page": 1}
            ],
            "scoring_factors": [
                {
                    "category": "施工组织设计评审",
                    "item": "资源配置计划",
                    "sub_item": None,
                    "points": 6,
                    "standard": None,
                    "page": 1,
                },
                {
                    "category": "施工组织设计评审",
                    "item": "设备配备计划",
                    "sub_item": "7.1",
                    "points": 2,
                    "standard": "x",
                    "page": 1,
                },
            ],
            "price_scoring": {},
            "final_score_rule": "",
            "veto_conditions": [],
        },
        "instructions_appendix": {
            "items": [
                {"clause": "1.4.1", "item": "资格", "content": "ditbj...", "page": 14}
            ]
        },
        "qualification": {"review_method": "资格后审", "conditions": [], "required_documents": []},
        "bid_format": {"items": [{"no": "一", "title": "投标函", "page": 1, "sub_items": []}]},
        "key_dates": [{"event": "开标", "datetime": "2023", "page": 1}],
        "duration": {"days": 1, "start_date": "a", "completion_date": "b", "page": 1},
    }

    markdown = render_markdown(result)

    assert "目录（自动解析）" in markdown
    assert "分值校验" in markdown
    assert "1.4.1" in markdown
    assert "关键时间节点" in markdown


class FakeSectionClient:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def extract_section(self, key, prompt, max_tokens=8000):
        self.calls.append((key, prompt, max_tokens))
        return self.payloads.pop(0)


def test_extract_appendix_batches_and_merges(monkeypatch):
    monkeypatch.setattr(extractor, "render_pages", lambda *args, **kwargs: "row\n" * 100)
    monkeypatch.setattr(extractor, "split_context", lambda context, limit: ["p1", "p2"])
    client = FakeSectionClient([
        {"items": [{"clause": "1.1", "item": "A", "content": "短"}]},
        {
            "items": [
                {"clause": "1.1", "item": "A", "content": "更长的内容"},
                {"clause": "2.1", "item": "B", "content": "x"},
            ]
        },
    ])

    result = extractor._extract_appendix(client, [])

    assert len(result["items"]) == 2
    assert next(item for item in result["items"] if item["clause"] == "1.1")["content"] == "更长的内容"
    assert len(client.calls) == 2


def test_extract_evaluation_merges_scoring(monkeypatch):
    client = FakeSectionClient([
        {"method": "综合评估法", "points_breakdown": [{"item": "A", "points": 100}]},
        {"scoring_factors": [{"category": "A", "item": "a", "sub_item": None, "points": 1}]},
        {"scoring_factors": [{"category": "B", "item": "b", "sub_item": None, "points": 2}]},
    ])

    result = extractor._extract_evaluation(client, [])

    assert result["method"] == "综合评估法"
    assert len(result["scoring_factors"]) == 2
    assert len(client.calls) == 3


def test_check_provenance_flags_bad_page_and_quote():
    blocks = [
        {
            "page": 1,
            "text": "招标人名称：北京市密云区太师屯镇人民政府",
            "type": "text",
        }
    ]
    good = {
        "project_overview": {
            "fields": [
                {
                    "name": "招标人",
                    "value": "北京市密云区太师屯镇人民政府",
                    "page": 1,
                    "quote": "北京市密云区太师屯镇人民政府",
                }
            ]
        }
    }
    assert check_provenance(good, blocks) == []

    bad = {
        "project_overview": {
            "fields": [{"name": "越界", "value": "x", "page": 99, "quote": "..."}]
        },
        "key_dates": [
            {"event": "开标", "datetime": "2023", "page": 1, "quote": "完全不存在的引用内容"}
        ],
    }
    issues = check_provenance(bad, blocks)
    assert any(issue["issue"] == "page_out_of_range" for issue in issues)
    assert any(issue["issue"] == "quote_not_found_on_page" for issue in issues)


def test_extract_document_uses_cache_and_includes_toc(settings, make_pdf, monkeypatch):
    pdf = make_pdf()
    sha1 = sha1_file(pdf)
    doc_id = make_doc_id(pdf, sha1)
    doc_dir = settings.data_dir / "parsed" / doc_id
    parts_dir = doc_dir / "extraction_parts"
    parts_dir.mkdir(parents=True)
    (doc_dir / "blocks.json").write_text(
        json.dumps([
            {"text": "第一章 招标公告.... 1", "page": 6, "type": "text", "level": 0},
            {"text": "正文", "page": 9, "type": "text", "level": 0},
        ]),
        encoding="utf-8",
    )
    part_payloads = {
        "project_overview": {"fields": [{"name": "项目名称", "value": "X", "page": 9}]},
        "instructions_appendix": {"items": []},
        "evaluation": {"method": "综合评估法", "scoring_factors": []},
        "qualification": {"review_method": "资格后审", "conditions": [], "required_documents": []},
        "bid_format": {"items": []},
        "key_dates": {"key_dates": [{"event": "开标", "datetime": "2023", "page": 9}], "duration": None},
    }
    for name, payload in part_payloads.items():
        (parts_dir / f"{name}.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )

    class NoCallExtractor:
        def __init__(self, *args, **kwargs):
            pass

        def extract_section(self, *args, **kwargs):
            raise AssertionError("should reuse cached parts")

        def json_call(self, *args, **kwargs):
            raise AssertionError("should reuse cached parts")

    monkeypatch.setattr(extractor, "DeepSeekExtractor", NoCallExtractor)

    json_path, md_path, result = extractor.extract_document(pdf, settings)

    assert result["toc"][0]["title"] == "第一章 招标公告"
    assert json_path.exists()
    assert "目录（自动解析）" in md_path.read_text(encoding="utf-8")
