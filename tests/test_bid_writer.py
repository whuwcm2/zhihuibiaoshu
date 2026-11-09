from __future__ import annotations

import json
from pathlib import Path

from docx import Document

from zhibiao import bid_writer
from zhibiao.bid_writer import (
    BidGraph,
    _renumber_sections,
    _rule_audit,
    assemble_markdown,
    build_scoring_report,
)
from zhibiao.profile import PLACEHOLDER, normalize_profile


class FakeLLM:
    def __init__(self):
        self.calls = []

    def complete_text(self, system, user, max_tokens=8000):
        self.calls.append(user[:20])
        if "施工组织设计" in user:
            return (
                "### 1. 内容完整性和编制水平\n\n"
                "按招标文件要求编制，项目经理【待填写】。"
            )
        if "商务部分" in user:
            return (
                "## 商务部分\n\n"
                "| 资格条件 | 投标人响应 |\n"
                "|---|---|\n"
                "| 资质 | 【待填写】 |"
            )
        return "### 一、投标函及投标函附录\n\n投标函：投标人【待填写】。"

    def complete_json(self, system, user, max_tokens=4000):
        return {
            "issues": [
                {
                    "section": "商务部分",
                    "issue": "资质证书编号待补充",
                    "severity": "high",
                    "suggestion": "填写资质证书编号",
                }
            ],
            "placeholder_count": 4,
            "fabrication_risk": False,
            "summary": "存在待填写项",
        }


def _tender() -> dict:
    return {
        "project_overview": {
            "fields": [
                {"name": "项目名称", "value": "测试供水工程"},
                {"name": "招标人", "value": "测试招标人"},
            ]
        },
        "evaluation": {
            "scoring_factors": [
                {
                    "category": "施工组织设计评审",
                    "item": "内容完整性和编制水平",
                    "points": 4,
                    "standard": "内容完整得满分",
                },
                {
                    "category": "其他评分因素",
                    "item": "投标人的业绩",
                    "points": 3,
                    "standard": "每项 1 分",
                },
            ]
        },
        "qualification": {
            "review_method": "资格后审",
            "conditions": [
                {"category": "资质条件", "requirement": "水利水电三级及以上"}
            ],
            "required_documents": [
                {"document": "营业执照", "requirement": "有效"}
            ],
        },
        "bid_format": {
            "items": [
                {
                    "no": "一",
                    "title": "投标函及投标函附录",
                    "sub_items": [{"title": "（一）投标函"}],
                }
            ]
        },
        "key_dates": [{"event": "投标截止", "datetime": "2026-01-01 09:00"}],
        "duration": {
            "days": 100,
            "start_date": "2026-01-02",
            "completion_date": "2026-04-11",
        },
    }


def test_graph_generates_markdown_with_placeholders():
    state = BidGraph(FakeLLM()).run("doc-1", _tender(), normalize_profile({}))

    assert "测试供水工程" in state["final_markdown"]
    assert "第一部分 商务部分" in state["final_markdown"]
    assert "第二部分 技术部分" in state["final_markdown"]
    assert "第三部分 投标文件格式" in state["final_markdown"]
    assert PLACEHOLDER in state["final_markdown"]
    assert "占位符" in state["review"]["summary"]
    assert len(state["outline"]["technical_factors"]) == 1
    assert len(state["outline"]["commercial_factors"]) == 1


def test_renumber_sections_removes_batch_and_subitem_numbers():
    markdown = "### 1. 内容\n### 2. 方案\n### 1. 质量\n### 7.2 劳动力计划（子项）"

    renumbered = _renumber_sections(markdown)

    assert "### 1. 内容" in renumbered
    assert "### 2. 方案" in renumbered
    assert "### 3. 质量" in renumbered
    assert "### 4. 劳动力计划（子项）" in renumbered


def test_build_scoring_report():
    report = build_scoring_report(
        _tender(), "### 内容完整性和编制水平\n本项已覆盖。"
    )

    assert report["total_points"] == 4
    assert report["covered_points"] == 4
    assert report["coverage_rate"] == 1
    assert report["items"][0]["covered"] is True


def test_rule_audit_uses_format_keyword_and_flags_unknown_company():
    tender = {
        "evaluation": {
            "scoring_factors": [
                {
                    "category": "施工组织设计评审",
                    "item": "内容完整性和编制水平",
                    "points": 4,
                }
            ]
        },
        "qualification": {"conditions": []},
        "bid_format": {
            "items": [{"no": "一", "title": "投标函及投标函附录", "sub_items": []}]
        },
    }
    technical = "### 内容完整性和编制水平\n内容"
    commercial = "### 投标函\n### 项目管理机构\n虚构建设有限公司"

    result = _rule_audit(tender, normalize_profile({}), technical, commercial)

    assert not any("未覆盖格式项" in issue["issue"] for issue in result["issues"])
    assert any(
        "未在输入资料中的公司名称" in issue["issue"] for issue in result["issues"]
    )
    assert result["fabrication_risk"] is True


def test_assemble_markdown_cover_and_appendix():
    state = {
        "tender": _tender(),
        "profile": normalize_profile({}),
        "commercial": "## 商务部分\n内容",
        "technical": "## 施工组织设计\n内容",
        "format_text": "## 投标文件格式\n内容",
        "review": {
            "issues": [
                {"section": "全文", "issue": "待补资料", "severity": "medium", "suggestion": "补充"}
            ],
            "placeholder_count": 2,
            "fabrication_risk": False,
            "summary": "摘要",
        },
    }

    markdown = assemble_markdown(state)

    assert markdown.startswith("# 测试供水工程 投标文件")
    assert "投标人：【待填写】" in markdown
    assert "### 商务部分" in markdown
    assert "## 附录 编制说明与待核对事项" not in markdown
    assert "# 附录 编制说明与待核对事项" in markdown
    assert "占位符数量：2" in markdown


def test_write_bid_accepts_inline_profile(settings, tmp_path, monkeypatch):
    parsed_dir = settings.data_dir / "parsed" / "doc-1"
    parsed_dir.mkdir(parents=True)
    (parsed_dir / "extraction.json").write_text(
        json.dumps(_tender(), ensure_ascii=False), encoding="utf-8"
    )
    monkeypatch.setattr(bid_writer, "DeepSeekChat", lambda current_settings: FakeLLM())

    result = bid_writer.write_bid(
        "doc-1",
        settings=settings,
        profile={"company_name": "测试建设有限公司"},
        output_dir=tmp_path / "bid_output",
        export_docx=False,
    )

    markdown = result["markdown_path"].read_text(encoding="utf-8")
    assert "测试建设有限公司" in markdown


def test_write_bid_writes_artifacts(settings, tmp_path, monkeypatch):
    parsed_dir = settings.data_dir / "parsed" / "doc-1"
    parsed_dir.mkdir(parents=True)
    (parsed_dir / "extraction.json").write_text(
        json.dumps(_tender(), ensure_ascii=False), encoding="utf-8"
    )
    monkeypatch.setattr(bid_writer, "DeepSeekChat", lambda current_settings: FakeLLM())

    result = bid_writer.write_bid(
        "doc-1",
        settings=settings,
        profile_path=None,
        output_dir=tmp_path / "bid_output",
    )

    assert result["markdown_path"].exists()
    assert result["docx_path"].exists()
    assert (result["agent_dir"] / "technical.md").exists()
    assert (result["agent_dir"] / "commercial.md").exists()
    assert (result["agent_dir"] / "format.md").exists()
    assert (result["agent_dir"] / "review.json").exists()
    assert (result["output_dir"] / "bid_meta.json").exists()
    document = Document(str(result["docx_path"]))
    assert any("测试供水工程" in paragraph.text for paragraph in document.paragraphs)
    assert result["placeholder_count"] > 0
    meta = json.loads(
        (result["output_dir"] / "bid_meta.json").read_text(encoding="utf-8")
    )
    markdown = result["markdown_path"].read_text(encoding="utf-8")
    assert f"占位符数量：{meta['placeholder_count']}" in markdown
    assert f"占位符 {meta['placeholder_count']} 处" in markdown
    assert meta["scoring_report"]["total_points"] == 4
