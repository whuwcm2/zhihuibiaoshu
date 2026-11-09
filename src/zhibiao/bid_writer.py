from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph
from langsmith import traceable

from .config import Settings, get_settings
from .docx_export import export_markdown_to_docx
from .llm import DeepSeekChat, LLMError
from .profile import (
    PLACEHOLDER,
    load_profile,
    missing_fields,
    normalize_profile,
    profile_json,
)
from .prompts import PromptHub

TECHNICAL_CATEGORY = "施工组织设计评审"


class BidState(TypedDict, total=False):
    doc_id: str
    tender: dict[str, Any]
    profile: dict[str, Any]
    outline: dict[str, Any]
    technical: str
    commercial: str
    format_text: str
    review: dict[str, Any]
    final_markdown: str


def load_tender(doc_id: str, settings: Settings) -> dict[str, Any]:
    path = settings.data_dir / "parsed" / doc_id / "extraction.json"
    if not path.exists():
        raise FileNotFoundError(
            f"未找到 {path}\n请先运行 ingest 和 extract：\n"
            f"  uv run zhibiao ingest <pdf>\n"
            f"  uv run zhibiao extract <pdf>"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _field(tender: dict[str, Any], name: str) -> str:
    fields = (tender.get("project_overview") or {}).get("fields") or []
    for field in fields:
        if field.get("name") == name and field.get("value") not in (None, ""):
            return str(field["value"])
    return PLACEHOLDER


def _overview_text(tender: dict[str, Any]) -> str:
    fields = (tender.get("project_overview") or {}).get("fields") or []
    lines = [
        f"- {field.get('name')}：{field.get('value') or PLACEHOLDER}"
        for field in fields
    ]
    return "\n".join(lines) or f"- 项目概况：{PLACEHOLDER}"


def _factor_line(factor: dict[str, Any]) -> str:
    sub_item = factor.get("sub_item")
    label = str(factor.get("item") or "")
    if sub_item:
        label = f"{label}（子项 {sub_item}）"
    return (
        f"- [{factor.get('category')}] {label}，{factor.get('points')} 分："
        f"{factor.get('standard') or PLACEHOLDER}"
    )


def _technical_factors(tender: dict[str, Any]) -> list[dict[str, Any]]:
    factors = (tender.get("evaluation") or {}).get("scoring_factors") or []
    return [
        factor
        for factor in factors
        if TECHNICAL_CATEGORY in str(factor.get("category") or "")
    ]


def _commercial_factors(tender: dict[str, Any]) -> list[dict[str, Any]]:
    factors = (tender.get("evaluation") or {}).get("scoring_factors") or []
    return [
        factor
        for factor in factors
        if TECHNICAL_CATEGORY not in str(factor.get("category") or "")
    ]


def _qualification_text(tender: dict[str, Any]) -> str:
    qualification = tender.get("qualification") or {}
    lines = [f"审查方式：{qualification.get('review_method') or PLACEHOLDER}"]
    for condition in qualification.get("conditions") or []:
        lines.append(
            f"- [{condition.get('category')}] {condition.get('requirement')}"
        )
    for document in qualification.get("required_documents") or []:
        lines.append(
            f"- 材料：{document.get('document')}；要求：{document.get('requirement')}"
        )
    return "\n".join(lines) or f"- 资格条件：{PLACEHOLDER}"


def _format_text(tender: dict[str, Any]) -> str:
    bid_format = tender.get("bid_format") or {}
    return _format_items_text(bid_format.get("items") or [])


def _format_items_text(items: list[dict[str, Any]]) -> str:
    lines = []
    for item in items:
        title = f"{item.get('no') or ''}、{item.get('title') or ''}".strip("、")
        lines.append(f"- {title}")
        for sub_item in item.get("sub_items") or []:
            lines.append(f"  - {sub_item.get('title')}")
    return "\n".join(lines) or f"- 格式清单：{PLACEHOLDER}"


def _without_heading(text: str, heading: str) -> str:
    text = text.strip()
    text = re.sub(r"^#+\s*" + re.escape(heading) + r"\s*", "", text)
    return text.strip()


def _key_dates_text(tender: dict[str, Any]) -> str:
    lines = []
    for item in tender.get("key_dates") or []:
        lines.append(f"- {item.get('event')}：{item.get('datetime') or PLACEHOLDER}")
    duration = tender.get("duration") or {}
    if duration:
        lines.append(
            f"- 工期：{duration.get('days') or PLACEHOLDER} 天；"
            f"计划开工 {duration.get('start_date') or PLACEHOLDER}；"
            f"计划完工 {duration.get('completion_date') or PLACEHOLDER}"
        )
    return "\n".join(lines) or f"- 关键时间：{PLACEHOLDER}"


def build_scoring_report(
    tender: dict[str, Any], technical_markdown: str
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    total_points = 0.0
    covered_points = 0.0
    for factor in _technical_factors(tender):
        item = str(factor.get("item") or "")
        try:
            points = float(factor.get("points"))
        except (TypeError, ValueError):
            points = 0.0
        covered = bool(item and item in technical_markdown)
        total_points += points
        if covered:
            covered_points += points
        items.append(
            {
                "category": factor.get("category"),
                "item": item,
                "sub_item": factor.get("sub_item"),
                "points": factor.get("points"),
                "covered": covered,
            }
        )
    return {
        "items": items,
        "total_points": total_points,
        "covered_points": covered_points,
        "coverage_rate": (covered_points / total_points) if total_points else 0.0,
    }


def build_outline(tender: dict[str, Any]) -> dict[str, Any]:
    technical = _technical_factors(tender)
    commercial = _commercial_factors(tender)
    return {
        "technical_factors": [
            {
                "item": factor.get("item"),
                "sub_item": factor.get("sub_item"),
                "points": factor.get("points"),
            }
            for factor in technical
        ],
        "commercial_factors": [
            {
                "category": factor.get("category"),
                "item": factor.get("item"),
                "points": factor.get("points"),
            }
            for factor in commercial
        ],
        "format_items": [
            {
                "no": item.get("no"),
                "title": item.get("title"),
                "sub_items": [sub.get("title") for sub in item.get("sub_items") or []],
            }
            for item in (tender.get("bid_format") or {}).get("items") or []
        ],
    }




def _headings(markdown: str) -> str:
    lines = [line.strip() for line in markdown.splitlines() if line.startswith("#")]
    return "\n".join(lines) or "（无标题）"



def _ensure_heading(text: str, heading: str) -> str:
    cleaned = text.strip()
    if not cleaned:
        return f"{heading}\n\n{PLACEHOLDER}"
    if not cleaned.startswith("#"):
        cleaned = f"{heading}\n\n{cleaned}"
    return cleaned


def _fallback_review(tender: dict[str, Any], draft: str, error: Exception) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    for factor in _technical_factors(tender):
        item = str(factor.get("item") or "")
        if item and item not in draft:
            issues.append(
                {
                    "section": "施工组织设计",
                    "issue": f"未覆盖评分因素：{item}",
                    "severity": "high",
                    "suggestion": f"补充“{item}”章节并对应评分标准",
                }
            )
    placeholder_count = draft.count(PLACEHOLDER)
    if placeholder_count == 0:
        issues.append(
            {
                "section": "全文",
                "issue": "未发现【待填写】占位符，可能存在编造风险",
                "severity": "high",
                "suggestion": "核对所有投标人信息是否来自 bidder_profile.json",
            }
        )
    return {
        "issues": issues,
        "placeholder_count": placeholder_count,
        "fabrication_risk": placeholder_count == 0,
        "summary": f"技术标 LLM 审查不可用，已使用规则审查：{error}",
    }


def _fallback_commercial_review(
    tender: dict[str, Any], draft: str, error: Exception
) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    for condition in (tender.get("qualification") or {}).get("conditions") or []:
        requirement = str(condition.get("requirement") or "")
        if requirement and requirement[:20] not in draft:
            issues.append(
                {
                    "section": "商务部分",
                    "issue": f"未覆盖资格条件：{requirement[:40]}",
                    "severity": "high",
                    "suggestion": "补充资格审查响应",
                }
            )
    placeholder_count = draft.count(PLACEHOLDER)
    if placeholder_count == 0:
        issues.append(
            {
                "section": "商务部分",
                "issue": "未发现【待填写】占位符，可能存在编造风险",
                "severity": "high",
                "suggestion": "核对投标人信息是否来自 bidder_profile.json",
            }
        )
    return {
        "issues": issues,
        "placeholder_count": placeholder_count,
        "fabrication_risk": placeholder_count == 0,
        "summary": f"商务/格式 LLM 审查不可用，已使用规则审查：{error}",
    }


def _filter_false_missing_issues(
    issues: list[dict[str, Any]], draft: str
) -> list[dict[str, Any]]:
    """过滤“缺投标函/保证金”这类与草稿标题明显矛盾的 LLM 误报。"""
    filtered: list[dict[str, Any]] = []
    for issue in issues:
        text = str(issue.get("issue") or "")
        if (
            "投标函" in text
            and "保证金" in text
            and "投标函" in draft
            and "保证金" in draft
        ):
            continue
        if "待填写" in text and "未补全" in text:
            continue
        filtered.append(issue)
    return filtered


def _dedupe_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    result: list[dict[str, Any]] = []
    for issue in issues:
        key = (str(issue.get("section")), str(issue.get("issue")))
        if key in seen:
            continue
        seen.add(key)
        result.append(issue)
    return result


def _rule_audit(
    tender: dict[str, Any],
    profile: dict[str, Any],
    technical: str,
    commercial_draft: str,
) -> dict[str, Any]:
    """确定性审计：评分因素/资格/格式覆盖、占位符、未授权公司名称。"""
    issues: list[dict[str, Any]] = []
    for factor in _technical_factors(tender):
        item = str(factor.get("item") or "")
        if item and item not in technical:
            issues.append(
                {
                    "section": "施工组织设计",
                    "issue": f"未覆盖评分因素：{item}",
                    "severity": "high",
                    "suggestion": f"补充“{item}”章节",
                }
            )

    for condition in (tender.get("qualification") or {}).get("conditions") or []:
        category = str(condition.get("category") or "")
        keyword = re.sub(r"(要求|资格)$", "", category).strip() or category
        if keyword and keyword not in commercial_draft:
            issues.append(
                {
                    "section": "商务部分",
                    "issue": f"未覆盖资格类别：{category}",
                    "severity": "high",
                    "suggestion": "补充资格审查响应",
                }
            )

    for item in (tender.get("bid_format") or {}).get("items") or []:
        title = str(item.get("title") or "")
        keyword = re.split(r"[及与]", title)[0].strip()
        keyword = re.sub(r"(表|文件)$", "", keyword).strip() or title
        if keyword and keyword not in commercial_draft:
            issues.append(
                {
                    "section": "投标文件格式",
                    "issue": f"未覆盖格式项：{title}",
                    "severity": "medium",
                    "suggestion": "补充该格式文件",
                }
            )

    draft = technical + "\n\n" + commercial_draft
    placeholder_count = draft.count(PLACEHOLDER)
    if placeholder_count == 0:
        issues.append(
            {
                "section": "全文",
                "issue": "未发现【待填写】占位符，可能存在编造风险",
                "severity": "high",
                "suggestion": "核对投标人信息是否来自 bidder_profile.json",
            }
        )

    allowed = json.dumps(tender, ensure_ascii=False) + json.dumps(
        profile, ensure_ascii=False
    )
    generic_prefixes = ("本公司", "我公司", "贵公司", "该公司")
    unknown = [
        name
        for name in sorted(set(re.findall(r"[一-龥]{2,30}有限公司", draft)))
        if name != "有限公司"
        and not name.startswith(generic_prefixes)
        and name not in allowed
    ]
    for name in unknown:
        issues.append(
            {
                "section": "全文",
                "issue": f"出现未在输入资料中的公司名称：{name}",
                "severity": "high",
                "suggestion": "核对该名称来源，禁止编造",
            }
        )

    return {
        "issues": issues,
        "placeholder_count": placeholder_count,
        "fabrication_risk": bool(unknown or placeholder_count == 0),
        "summary": "规则审计",
    }


def _renumber_sections(markdown: str) -> str:
    """把各批次生成的三级标题重新连续编号，去掉 LLM 自带的分值/子项编号。"""
    lines: list[str] = []
    index = 0
    for line in markdown.splitlines():
        if line.startswith("### "):
            title = re.sub(r"^\d+(?:\.\d+)*[.、]?\s*", "", line[4:].strip())
            index += 1
            line = f"### {index}. {title}"
        lines.append(line)
    return "\n".join(lines)


def _demote_headings(markdown: str) -> str:
    lines = []
    for line in markdown.splitlines():
        if line.startswith("#"):
            level = len(line) - len(line.lstrip("#"))
            if level < 5:
                line = "#" + line
        lines.append(line)
    return "\n".join(lines).strip()


def _review_markdown(review: dict[str, Any]) -> str:
    issues = review.get("issues") or []
    lines = [
        f"- 占位符数量：{review.get('placeholder_count', 0)}",
        f"- 编造风险：{'是' if review.get('fabrication_risk') else '否'}",
        f"- 审查摘要：{review.get('summary') or '无'}",
    ]
    if issues:
        lines += ["", "### 待核对事项", ""]
        for issue in issues:
            lines.append(
                f"- [{issue.get('severity')}] {issue.get('section')}："
                f"{issue.get('issue')}（建议：{issue.get('suggestion')}）"
            )
    else:
        lines.append("- 审查未发现明显问题，仍需人工核对全部【待填写】项。")
    return "\n".join(lines)


def assemble_markdown(state: BidState) -> str:
    tender = state["tender"]
    profile = state["profile"]
    project_name = _field(tender, "项目名称")
    company_name = str(profile.get("company_name") or PLACEHOLDER)
    review = state.get("review") or {}

    parts = [
        f"# {project_name} 投标文件",
        "",
        f"投标人：{company_name}",
        "",
        "编制日期：【待填写】",
        "",
        "> 本文件依据招标文件和投标人资料自动生成。所有【待填写】处必须由投标人补充真实信息并核对后再提交。",
        "",
        "## 目录",
        "",
        "- 第一部分 商务部分",
        "- 第二部分 技术部分（施工组织设计）",
        "- 第三部分 投标文件格式",
        "- 附录 编制说明与待核对事项",
        "",
        "# 第一部分 商务部分",
        "",
        _demote_headings(state.get("commercial", "")),
        "",
        "# 第二部分 技术部分",
        "",
        _demote_headings(state.get("technical", "")),
        "",
        "# 第三部分 投标文件格式",
        "",
        _demote_headings(state.get("format_text", "")),
        "",
        "# 附录 编制说明与待核对事项",
        "",
        _review_markdown(review),
    ]
    return "\n".join(parts).strip() + "\n"


class BidGraph:
    def __init__(
        self,
        llm: DeepSeekChat,
        progress: Callable[[str], None] | None = None,
        prompt_hub: PromptHub | None = None,
    ) -> None:
        self.llm = llm
        self.progress = progress
        self.prompts = prompt_hub or PromptHub()
        self.graph = self._build()

    def _notify(self, stage: str) -> None:
        if self.progress:
            self.progress(stage)

    def _planner(self, state: BidState) -> dict[str, Any]:
        self._notify("planner")
        outline = build_outline(state["tender"])
        print(
            f"[agent] planner: {len(outline['technical_factors'])} 个技术评分因素，"
            f"{len(outline['format_items'])} 个格式项",
            flush=True,
        )
        return {"outline": outline}

    def _generate_sections(
        self,
        items: list[dict[str, Any]],
        prompt_name: str,
        variables_builder,
        heading: str,
        max_tokens: int,
        label: str,
    ) -> list[str]:
        if not items:
            return [PLACEHOLDER]
        try:
            system, user = self.prompts.render(
                prompt_name, **variables_builder(items)
            )
            text = self.llm.complete_text(system, user, max_tokens=max_tokens)
            return [_without_heading(text, heading)]
        except LLMError as exc:
            if "截断" in str(exc) and len(items) > 1:
                middle = len(items) // 2
                print(
                    f"[agent] {label}: 输出截断，拆分为 {len(items)} -> "
                    f"{middle}+{len(items) - middle} 项重试",
                    flush=True,
                )
                return self._generate_sections(
                    items[:middle],
                    prompt_name,
                    variables_builder,
                    heading,
                    max_tokens,
                    label,
                ) + self._generate_sections(
                    items[middle:],
                    prompt_name,
                    variables_builder,
                    heading,
                    max_tokens,
                    label,
                )
            raise

    def _technical_writer(self, state: BidState) -> dict[str, Any]:
        self._notify("technical_writer")
        factors = _technical_factors(state["tender"])
        groups = [factors[index:index + 4] for index in range(0, len(factors), 4)] or [[]]
        chunks: list[str] = []
        for index, group in enumerate(groups, start=1):
            print(
                f"[agent] technical_writer {index}/{len(groups)}: 编写施工组织设计…",
                flush=True,
            )
            chunks.extend(
                self._generate_sections(
                    group,
                    "zhibiao-technical-writer",
                    lambda items: {
                        "overview": _overview_text(state["tender"]),
                        "key_dates": _key_dates_text(state["tender"]),
                        "scoring": "\n".join(_factor_line(factor) for factor in items)
                        or f"- {PLACEHOLDER}",
                        "profile_json": profile_json(state["profile"]),
                    },
                    "施工组织设计",
                    6000,
                    f"technical_writer {index}",
                )
            )
        body = "\n\n".join(chunk for chunk in chunks if chunk.strip()) or PLACEHOLDER
        return {"technical": f"## 施工组织设计\n\n{_renumber_sections(body)}"}

    def _generate_commercial_qualification(
        self,
        tender: dict[str, Any],
        profile: dict[str, Any],
        conditions: list[dict[str, Any]],
        include_documents: bool,
        label: str,
    ) -> list[str]:
        condition_lines = "\n".join(
            f"- [{condition.get('category')}] {condition.get('requirement')}"
            for condition in conditions
        ) or f"- {PLACEHOLDER}"
        documents_text = ""
        if include_documents:
            documents = "\n".join(
                f"- {document.get('document')}："
                f"{document.get('requirement') or PLACEHOLDER}"
                for document in (tender.get("qualification") or {}).get(
                    "required_documents"
                ) or []
            ) or f"- {PLACEHOLDER}"
            documents_text = f"\n【需提交的证明材料】\n{documents}\n"
        try:
            system, user = self.prompts.render(
                "zhibiao-commercial-qualification",
                overview=_overview_text(tender),
                conditions=condition_lines,
                documents_text=documents_text,
                profile_json=profile_json(profile),
            )
            text = self.llm.complete_text(system, user, max_tokens=6000)
            return [_without_heading(text, "商务部分")]
        except LLMError as exc:
            if "截断" in str(exc) and len(conditions) > 1:
                middle = len(conditions) // 2
                print(
                    f"[agent] {label}: 输出截断，拆分为 {len(conditions)} -> "
                    f"{middle}+{len(conditions) - middle} 项重试",
                    flush=True,
                )
                return self._generate_commercial_qualification(
                    tender, profile, conditions[:middle], False, label
                ) + self._generate_commercial_qualification(
                    tender, profile, conditions[middle:], include_documents, label
                )
            raise

    def _commercial_writer(self, state: BidState) -> dict[str, Any]:
        self._notify("commercial_writer")
        qualification = (
            (state["tender"].get("qualification") or {}).get("conditions") or []
        )
        groups = [
            qualification[index:index + 8]
            for index in range(0, len(qualification), 8)
        ] or [[]]
        chunks: list[str] = []
        for index, group in enumerate(groups, start=1):
            print(
                f"[agent] commercial_writer 资格审查资料 {index}/{len(groups)}…",
                flush=True,
            )
            chunks.extend(
                self._generate_commercial_qualification(
                    state["tender"],
                    state["profile"],
                    group,
                    include_documents=(index == len(groups)),
                    label=f"commercial_qualification {index}",
                )
            )

        print("[agent] commercial_writer 项目管理机构与商务评分…", flush=True)
        chunks.extend(
            self._generate_sections(
                _commercial_factors(state["tender"]),
                "zhibiao-commercial-scoring",
                lambda items: {
                    "overview": _overview_text(state["tender"]),
                    "factors": "\n".join(_factor_line(factor) for factor in items)
                    or f"- {PLACEHOLDER}",
                    "profile_json": profile_json(state["profile"]),
                },
                "商务部分",
                6000,
                "commercial_scoring",
            )
        )
        body = "\n\n".join(chunk for chunk in chunks if chunk.strip()) or PLACEHOLDER
        return {"commercial": f"## 商务部分\n\n{body}"}

    def _format_writer(self, state: BidState) -> dict[str, Any]:
        self._notify("format_writer")
        items = (state["tender"].get("bid_format") or {}).get("items") or []
        groups = [items[index:index + 4] for index in range(0, len(items), 4)] or [[]]
        chunks: list[str] = []
        for index, group in enumerate(groups, start=1):
            print(
                f"[agent] format_writer {index}/{len(groups)}: 编写格式文件…",
                flush=True,
            )
            chunks.extend(
                self._generate_sections(
                    group,
                    "zhibiao-format-writer",
                    lambda items: {
                        "overview": _overview_text(state["tender"]),
                        "items": _format_items_text(items),
                        "key_dates": _key_dates_text(state["tender"]),
                        "profile_json": profile_json(state["profile"]),
                    },
                    "投标文件格式",
                    5000,
                    f"format_writer {index}",
                )
            )
        body = "\n\n".join(chunk for chunk in chunks if chunk.strip()) or PLACEHOLDER
        return {"format_text": f"## 投标文件格式\n\n{body}"}

    def _reviewer(self, state: BidState) -> dict[str, Any]:
        self._notify("reviewer")
        technical = state.get("technical", "")
        commercial_draft = "\n\n".join(
            [state.get("commercial", ""), state.get("format_text", "")]
        )

        print("[agent] reviewer 1/2: 技术标审查…", flush=True)
        try:
            scoring = "\n".join(
                f"- {factor.get('item')}（{factor.get('points')} 分）"
                for factor in _technical_factors(state["tender"])
            ) or f"- {PLACEHOLDER}"
            system, user = self.prompts.render(
                "zhibiao-reviewer-technical",
                scoring=scoring,
                headings=_headings(technical),
                missing="、".join(missing_fields(state["profile"])[:40]) or "无",
                placeholder_count=technical.count(PLACEHOLDER),
            )
            technical_review = self.llm.complete_json(system, user, max_tokens=3000)
        except Exception as exc:  # noqa: BLE001 - 审查失败不阻塞产物生成
            technical_review = _fallback_review(state["tender"], technical, exc)

        print("[agent] reviewer 2/2: 商务/格式审查…", flush=True)
        try:
            conditions = "\n".join(
                f"- [{condition.get('category')}] "
                f"{str(condition.get('requirement') or '')[:60]}"
                for condition in (state["tender"].get("qualification") or {}).get(
                    "conditions"
                ) or []
            ) or f"- {PLACEHOLDER}"
            formats = "\n".join(
                f"- {item.get('no') or ''}、{item.get('title') or ''}"
                for item in (state["tender"].get("bid_format") or {}).get("items")
                or []
            ) or f"- {PLACEHOLDER}"
            system, user = self.prompts.render(
                "zhibiao-reviewer-commercial",
                conditions=conditions,
                formats=formats,
                headings=_headings(commercial_draft),
                missing="、".join(missing_fields(state["profile"])[:40]) or "无",
                placeholder_count=commercial_draft.count(PLACEHOLDER),
            )
            commercial_review = self.llm.complete_json(system, user, max_tokens=3000)
        except Exception as exc:  # noqa: BLE001 - 审查失败不阻塞产物生成
            commercial_review = _fallback_commercial_review(
                state["tender"], commercial_draft, exc
            )

        rule_review = _rule_audit(
            state["tender"], state["profile"], technical, commercial_draft
        )
        issues = _filter_false_missing_issues(
            _dedupe_issues(
                (rule_review.get("issues") or [])
                + (technical_review.get("issues") or [])
                + (commercial_review.get("issues") or [])
            ),
            commercial_draft,
        )
        review = {
            "issues": issues,
            "placeholder_count": rule_review["placeholder_count"],
            "rule_issue_count": len(rule_review.get("issues") or []),
            # 编造风险以确定性规则审计为准；LLM 的 risk 标记仅作参考
            "fabrication_risk": bool(rule_review.get("fabrication_risk")),
            "summary": (
                f"规则审计 {len(rule_review.get('issues') or [])} 条；"
                f"编造风险：{'是' if rule_review.get('fabrication_risk') else '否'}；"
                f"占位符 {rule_review['placeholder_count']} 处；"
                f"审查问题 {len(issues)} 条（详见待核对事项）。"
            ),
        }
        return {"review": review}

    def _assembler(self, state: BidState) -> dict[str, Any]:
        self._notify("assembler")
        print("[agent] assembler: 合并并生成 Markdown…", flush=True)
        return {"final_markdown": assemble_markdown(state)}

    def _build(self):
        graph = StateGraph(BidState)
        graph.add_node("planner", self._planner)
        graph.add_node("technical_writer", self._technical_writer)
        graph.add_node("commercial_writer", self._commercial_writer)
        graph.add_node("format_writer", self._format_writer)
        graph.add_node("reviewer", self._reviewer)
        graph.add_node("assembler", self._assembler)

        graph.add_edge(START, "planner")
        graph.add_edge("planner", "technical_writer")
        graph.add_edge("technical_writer", "commercial_writer")
        graph.add_edge("commercial_writer", "format_writer")
        graph.add_edge("format_writer", "reviewer")
        graph.add_edge("reviewer", "assembler")
        graph.add_edge("assembler", END)
        return graph.compile()

    def run(self, doc_id: str, tender: dict[str, Any], profile: dict[str, Any]) -> BidState:
        return self.graph.invoke(
            {"doc_id": doc_id, "tender": tender, "profile": profile}
        )


@traceable(name="bid.write", run_type="chain")
def write_bid(
    doc_id: str,
    settings: Settings | None = None,
    profile_path: Path | None = None,
    profile: dict[str, Any] | None = None,
    output_dir: Path | None = None,
    export_docx: bool = True,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    tender = load_tender(doc_id, settings)
    profile_data = (
        normalize_profile(profile) if profile is not None else load_profile(profile_path)
    )
    target_dir = output_dir or (settings.data_dir / "bids" / doc_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    agent_dir = target_dir / "agent_outputs"
    agent_dir.mkdir(parents=True, exist_ok=True)

    print(f"[write] doc_id={doc_id}，输出目录={target_dir}", flush=True)
    llm = DeepSeekChat(settings)
    state = BidGraph(llm, progress=progress).run(doc_id, tender, profile_data)
    scoring_report = build_scoring_report(tender, state.get("technical", ""))

    if isinstance(state.get("review"), dict):
        # 最终稿包含封面/附录，先按最终稿回填占位符数量，再重新拼装
        state["review"]["placeholder_count"] = assemble_markdown(state).count(PLACEHOLDER)
    final_markdown = assemble_markdown(state)
    final_placeholder_count = final_markdown.count(PLACEHOLDER)
    if isinstance(state.get("review"), dict):
        review = state["review"]
        review["placeholder_count"] = final_placeholder_count
        review["summary"] = (
            f"规则审计 {review.get('rule_issue_count', 0)} 条；"
            f"编造风险：{'是' if review.get('fabrication_risk') else '否'}；"
            f"占位符 {final_placeholder_count} 处；"
            f"审查问题 {len(review.get('issues') or [])} 条（详见待核对事项）。"
        )
        final_markdown = assemble_markdown(state)
        final_placeholder_count = final_markdown.count(PLACEHOLDER)

    (agent_dir / "outline.json").write_text(
        json.dumps(state.get("outline") or {}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (agent_dir / "technical.md").write_text(state.get("technical", ""), encoding="utf-8")
    (agent_dir / "commercial.md").write_text(state.get("commercial", ""), encoding="utf-8")
    (agent_dir / "format.md").write_text(state.get("format_text", ""), encoding="utf-8")
    (agent_dir / "review.json").write_text(
        json.dumps(state.get("review") or {}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    markdown_path = target_dir / "bid.md"
    markdown_path.write_text(final_markdown, encoding="utf-8")

    docx_path: Path | None = None
    if export_docx:
        docx_path = export_markdown_to_docx(
            final_markdown,
            target_dir / "bid.docx",
            title=_field(tender, "项目名称"),
        )

    meta = {
        "doc_id": doc_id,
        "project_name": _field(tender, "项目名称"),
        "company_name": profile_data.get("company_name"),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "placeholder_count": final_placeholder_count,
        "review": state.get("review"),
        "scoring_report": scoring_report,
        "artifacts": {
            "markdown": str(markdown_path),
            "docx": str(docx_path) if docx_path else None,
            "agent_outputs": str(agent_dir),
        },
    }
    (target_dir / "bid_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"[done] Markdown: {markdown_path}", flush=True)
    if docx_path:
        print(f"[done] Word: {docx_path}", flush=True)
    print(
        f"[done] 占位符 {meta['placeholder_count']} 处，"
        f"审查问题 {len((state.get('review') or {}).get('issues') or [])} 条",
        flush=True,
    )
    return {
        "output_dir": target_dir,
        "markdown_path": markdown_path,
        "docx_path": docx_path,
        "agent_dir": agent_dir,
        "review": state.get("review"),
        "scoring_report": scoring_report,
        "placeholder_count": meta["placeholder_count"],
    }
