from __future__ import annotations

import json
import re
import time
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from langsmith import traceable
from langsmith.wrappers import wrap_openai
from openai import OpenAI

from .chunker import html_table_to_text
from .config import Settings
from .pipeline import make_doc_id, sha1_file
from .toc import toc_from_blocks

SYSTEM_PROMPT = """你是专业的招投标文件分析专家。请从招标文件原文中抽取结构化信息。

必须遵守：
1. 只输出一个合法 JSON 对象，不要输出解释、前后缀或 Markdown 代码块。
2. 必须忠实于原文，禁止推测、补全或编造。原文未明确写出的字段填 null。
3. 原文出现复选框并列（如“不要求/要求”）且无法判断选中项时，保留原文并标注“需核对原件”。
4. 金额、日期、天数、分值必须与原文逐字一致，不得四舍五入或改写。
5. 每条信息尽量附 page（PDF 页码，整数）和 quote（≤120 字原文摘录）。
6. “全量”抽取同类条目，不得只抽重点或合并条目。
"""


class ExtractionError(RuntimeError):
    pass


def load_blocks_for_pdf(pdf_path: Path, settings: Settings) -> tuple[str, Path, list[dict]]:
    sha1 = sha1_file(pdf_path)
    doc_id = make_doc_id(pdf_path, sha1)
    doc_dir = settings.data_dir / "parsed" / doc_id
    blocks_path = doc_dir / "blocks.json"
    if not blocks_path.exists():
        raise ExtractionError(
            f"未找到解析缓存：{blocks_path}\n请先运行：uv run zhibiao ingest {pdf_path}"
        )
    return doc_id, doc_dir, json.loads(blocks_path.read_text(encoding="utf-8"))


def render_pages(blocks: list[dict], start: int, end: int) -> str:
    """按页渲染 Markdown 上下文，附带 [PDF p.X] 页码标记。"""
    pages: dict[int, list[str]] = defaultdict(list)
    for block in blocks:
        page = int(block.get("page") or 0)
        if not (start <= page <= end):
            continue
        if block.get("type") in {"page_number", "header", "footer"}:
            continue
        text = str(block.get("text") or "").strip()
        if block.get("type") == "table":
            text = html_table_to_text(text).strip()
        if text:
            pages[page].append(text)
    return "\n\n".join(
        f"[PDF p.{page}]\n" + "\n\n".join(texts)
        for page, texts in sorted(pages.items())
    )


def split_context(context: str, max_chars: int) -> list[str]:
    """按行切分上下文，避免把表格行切断；每个片段保留最近的页码标记。"""
    lines = context.splitlines()
    parts: list[str] = []
    current: list[str] = []
    current_chars = 0
    last_page_marker = ""

    for line in lines:
        if line.startswith("[PDF p."):
            last_page_marker = line
        if current and current_chars + len(line) + 1 > max_chars:
            parts.append("\n".join(current))
            current = [last_page_marker] if last_page_marker else []
            current_chars = sum(len(item) + 1 for item in current)
        current.append(line)
        current_chars += len(line) + 1

    if current:
        parts.append("\n".join(current))
    return parts


def _merge_items(items: list[dict], keys: tuple[str, ...]) -> list[dict]:
    merged: dict[tuple[str, ...], dict] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        key = tuple(str(item.get(key_name) or "").strip() for key_name in keys)
        if not any(key):
            continue
        existing = merged.get(key)
        if existing is None or len(json.dumps(item, ensure_ascii=False)) > len(
            json.dumps(existing, ensure_ascii=False)
        ):
            merged[key] = item
    return list(merged.values())


def _provenance_items(result: dict):
    for item in (result.get("project_overview") or {}).get("fields") or []:
        yield "project_overview", item
    for item in (result.get("instructions_appendix") or {}).get("items") or []:
        yield "instructions_appendix", item

    evaluation = result.get("evaluation") or {}
    for section in ("preliminary_review", "scoring_factors", "veto_conditions"):
        for item in evaluation.get(section) or []:
            yield f"evaluation.{section}", item

    qualification = result.get("qualification") or {}
    for section in ("conditions", "required_documents"):
        for item in qualification.get(section) or []:
            yield f"qualification.{section}", item

    for item in (result.get("bid_format") or {}).get("items") or []:
        yield "bid_format.items", item
        for sub_item in item.get("sub_items") or []:
            yield "bid_format.sub_items", sub_item

    for item in result.get("key_dates") or []:
        yield "key_dates", item


def _normalize_quote(value: object) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def check_provenance(result: dict, blocks: list[dict]) -> list[dict]:
    """核对抽取项的页码是否存在、quote 是否能在对应页原文中找到。"""
    page_text: dict[int, list[str]] = defaultdict(list)
    for block in blocks:
        page = int(block.get("page") or 0)
        if page <= 0:
            continue
        text = str(block.get("text") or "")
        if block.get("type") == "table":
            text = html_table_to_text(text)
        page_text[page].append(text)
    valid_pages = set(page_text)
    issues: list[dict] = []

    for section, item in _provenance_items(result):
        if not isinstance(item, dict):
            continue
        label = str(
            item.get("name")
            or item.get("item")
            or item.get("event")
            or item.get("document")
            or item.get("title")
            or item.get("condition")
            or "?"
        )
        raw_page = item.get("page")
        if raw_page is None:
            continue
        try:
            page = int(raw_page)
        except (TypeError, ValueError):
            issues.append({"section": section, "item": label, "page": raw_page,
                           "issue": "page_missing_or_invalid"})
            continue
        if page not in valid_pages:
            issues.append({"section": section, "item": label, "page": page,
                           "issue": "page_out_of_range"})
            continue

        quote = _normalize_quote(item.get("quote"))
        if len(quote) < 10 or quote.startswith("来自"):
            continue
        page_content = _normalize_quote("\n".join(page_text[page]))
        if quote not in page_content:
            issues.append({"section": section, "item": label, "page": page,
                           "issue": "quote_not_found_on_page"})

    return issues


def _parse_json_text(content: str) -> dict:
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        start, end = content.find("{"), content.rfind("}")
        if start >= 0 and end > start:
            return json.loads(content[start:end + 1])
        raise


class DeepSeekExtractor:
    def __init__(self, settings: Settings) -> None:
        if not settings.deepseek_api_key:
            raise ExtractionError("DEEPSEEK_API_KEY 未配置")
        self.client = wrap_openai(
            OpenAI(
                api_key=settings.deepseek_api_key,
                base_url=settings.deepseek_base_url,
                timeout=240,
            )
        )
        self.model = settings.deepseek_model

    @traceable(name="deepseek.extract_json", run_type="chain")
    def json_call(self, prompt: str, max_tokens: int = 8000) -> dict:
        current_prompt = prompt
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": current_prompt},
                    ],
                    temperature=0,
                    max_tokens=max_tokens,
                    response_format={"type": "json_object"},
                )
                choice = response.choices[0]
                if choice.finish_reason == "length":
                    raise ExtractionError("LLM 输出被截断（finish_reason=length）")
                return _parse_json_text(choice.message.content or "")
            except Exception as exc:  # noqa: BLE001 - SDK 异常类型较杂
                last_error = exc
                current_prompt = (
                    prompt
                    + "\n\n上一次输出失败或不是合法 JSON，请重新只输出一个合法 JSON 对象。"
                )
                if attempt < 2:
                    time.sleep(2 * (attempt + 1))
        raise ExtractionError(f"LLM 抽取失败: {last_error}")

    def extract_section(self, key: str, prompt: str, max_tokens: int = 8000) -> dict | list:
        current_prompt = prompt
        for _ in range(2):
            payload = self.json_call(current_prompt, max_tokens=max_tokens)
            value = payload.get(key)
            if isinstance(value, (dict, list)):
                return value
            current_prompt = (
                prompt
                + f'\n\n上次输出缺少顶层键 "{key}"，请严格输出 {{"{key}": ...}} 格式。'
            )
        raise ExtractionError(f"LLM 输出缺少顶层键 {key}")


# ---------- 提示词 ----------

def _overview_prompt(blocks: list[dict]) -> str:
    context = "\n\n".join([render_pages(blocks, 9, 16), render_pages(blocks, 31, 33)])
    return f"""任务：从招标文件原文中抽取“项目概况”。
只输出 JSON：
{{
  "project_overview": {{
    "fields": [
      {{"name": "项目名称", "value": "...", "page": 14, "quote": "..."}},
      {{"name": "招标人", "value": "...", "page": 14, "quote": "..."}},
      {{"name": "招标代理机构", "value": "...", "page": 14, "quote": "..."}},
      {{"name": "建设地点", "value": "...", "page": 14, "quote": "..."}},
      {{"name": "招标范围/项目概况", "value": "...", "page": 9, "quote": "..."}},
      {{"name": "资金来源", "value": "...", "page": 31, "quote": "..."}},
      {{"name": "计划工期", "value": "...", "page": 14, "quote": "..."}},
      {{"name": "计划开工日期", "value": "...", "page": 14, "quote": "..."}},
      {{"name": "计划完工日期", "value": "...", "page": 14, "quote": "..."}},
      {{"name": "质量要求", "value": "...", "page": 14, "quote": "..."}},
      {{"name": "最高投标限价", "value": "...", "page": 14, "quote": "..."}},
      {{"name": "投标保证金", "value": "...", "page": 14, "quote": "..."}},
      {{"name": "投标有效期", "value": "...", "page": 14, "quote": "..."}},
      {{"name": "联合体投标", "value": "...", "page": 14, "quote": "..."}},
      {{"name": "资格审查方式", "value": "...", "page": 14, "quote": "..."}}
    ]
  }}
}}
要求：覆盖上述所有字段，顺序一致；value 必须来自原文，未明确填写时用 null 并在 quote 说明；金额、工期、日期必须逐字一致。
原文：
{context}"""


def _appendix_prompt(context: str) -> str:
    return f"""任务：全量抽取“投标人须知前附表”的条款行（输入可能是同一张表的一个片段）。
只输出 JSON：
{{"instructions_appendix": {{"items": [
  {{"clause": "1.1.2", "item": "招标人", "content": "...", "page": 14, "quote": "..."}}
]}}}}
要求：
- 按原文条款号顺序输出本片段中的全部完整条款行，不得合并、省略或只抽重点。
- 输入可能从表格中间开始或结束：只抽取完整成行的条款，跳过表头（条款号/条款名称/编列内容）、章节标题和残缺行。
- clause 填条款号；item 填条款名称；content 填编列内容，保留原文（包括复选框并列项）。
- 原文中独立列出的子条款（如 1.4.1、3.5.2）要单独成行。
- page 使用 [PDF p.X] 中的 X。
原文：
{context}"""


def _evaluation_base_prompt(blocks: list[dict]) -> str:
    context = render_pages(blocks, 53, 61)
    return f"""任务：抽取第三章“评标办法（综合评估法）”的初步评审标准、分值构成、报价规则、最终得分规则与否决投标情形。
只输出 JSON：
{{
  "evaluation": {{
    "method": "综合评估法",
    "total_points": 100,
    "points_breakdown": [
      {{"item": "施工组织设计评审", "points": 30, "page": 53}},
      {{"item": "项目管理机构评审", "points": 6, "page": 53}},
      {{"item": "投标报价", "points": 50, "page": 53}},
      {{"item": "其他评分因素", "points": 14, "page": 53}}
    ],
    "preliminary_review": [
      {{"category": "形式评审", "item": "投标人名称", "standard": "...", "page": 53}}
    ],
    "price_scoring": {{
      "base_price_rule": "...",
      "deviation_rule": "...",
      "deduction_rule": "...",
      "small_enterprise_rule": "...",
      "page": 53
    }},
    "final_score_rule": "...",
    "veto_conditions": [{{"condition": "...", "page": 60}}]
  }}
}}
要求：
- points_breakdown 四项合计必须为 100，分值与原文一致。
- preliminary_review 覆盖形式评审、资格评审、响应性评审的全部评审因素。
- price_scoring 完整保留评标基准价公式、偏差率、扣分规则、中小企业优惠原文。
- veto_conditions 覆盖 3.1.2 等条款列出的全部否决情形。
- 本条提示词不负责 scoring_factors，不要输出该字段。
- page 使用 [PDF p.X] 中的 X。
原文：
{context}"""


def _evaluation_scoring_prompt(blocks: list[dict], start: int, end: int) -> str:
    context = render_pages(blocks, start, end)
    return f"""任务：全量抽取评审打分表（表11）中第 {start}-{end} 页的评分因素、分值和评分标准。
只输出 JSON：
{{"evaluation": {{"scoring_factors": [
  {{"category": "施工组织设计评审", "item": "内容完整性和编制水平", "sub_item": null, "points": 4, "standard": "...", "page": 79}}
]}}}}
要求：
- 逐行抽取该页范围内的所有评分项，包括子项（如 7.1/7.2/7.3）；不得只给汇总。
- category 使用原文大类名称（施工组织设计评审 / 项目管理机构评审 / 投标报价 / 其他评分因素）；sub_item 用于 7.1、7.2 这类子项，没有则为 null。
- standard 完整保留每一档赋分区间和备注，不得概括。
- 分值与原文完全一致；page 使用 [PDF p.X] 中的 X。
原文：
{context}"""


def _qualification_prompt(blocks: list[dict]) -> str:
    context = "\n\n".join([
        render_pages(blocks, 9, 12),
        render_pages(blocks, 13, 30),
        render_pages(blocks, 72, 73),
    ])
    return f"""任务：全量抽取资格审查条件及需提交的证明材料。
只输出 JSON：
{{"qualification": {{
  "review_method": "资格后审",
  "conditions": [
    {{"category": "资质条件", "requirement": "...", "page": 14, "quote": "..."}},
    {{"category": "财务要求", "requirement": "...", "page": 14, "quote": "..."}},
    {{"category": "业绩要求", "requirement": "...", "page": 14, "quote": "..."}},
    {{"category": "信誉要求", "requirement": "...", "page": 14, "quote": "..."}},
    {{"category": "项目经理资格", "requirement": "...", "page": 14, "quote": "..."}},
    {{"category": "技术负责人资格", "requirement": "...", "page": 14, "quote": "..."}},
    {{"category": "其他人员要求", "requirement": "...", "page": 14, "quote": "..."}},
    {{"category": "联合体要求", "requirement": "...", "page": 14, "quote": "..."}},
    {{"category": "其他", "requirement": "...", "page": 14, "quote": "..."}}
  ],
  "required_documents": [{{"document": "营业执照", "requirement": "...", "page": 72}}]
}}}}
要求：
- 覆盖招标公告“3. 投标人资格要求”、投标人须知前附表 1.4.1/1.4.2/1.4.3、表6“投标人资格评审表”的全部条件。
- 资质等级、财务年份与金额、业绩年限与规模、项目经理专业与等级、安全生产考核证书、人员本单位要求、联合体、回避情形等必须逐条保留。
- 原文用“/”或空白表示无要求/未填写的，如实保留，不要编造。
- 复选框并列无法判断选中项的，保留原文并注明“需核对原件”。
- page 使用 [PDF p.X] 中的 X。
原文：
{context}"""


def _bid_format_prompt(blocks: list[dict]) -> str:
    context = render_pages(blocks, 180, 208)
    return f"""任务：全量列出第八章“投标文件格式”要求提交的全部格式文件及子项。
只输出 JSON：
{{"bid_format": {{
  "chapter_title": "第八章 投标文件格式",
  "items": [
    {{"no": "一", "title": "投标函及投标函附录", "page": 183,
      "sub_items": [{{"title": "（一）投标函", "page": 183}}]}}
  ],
  "notes": ["..."]
}}}}
要求：
- 以第 182 页目录的十一项为完整主清单（一至十一），逐项输出，不得遗漏“十、原件的复印件”“十一、其他资料”。
- 用正文标题补全每项的子格式和 PDF 页码；目录有但正文未检测到独立页面的项，page 填 null。
- 目录中“二、法定代表人身份证明”和“二、授权委托书”序号重复，按原文保留，并在 notes 说明。
- page 使用 [PDF p.X] 中的 X，不要使用目录里的印刷页码。
原文：
{context}"""


def _key_dates_prompt(context: str, focus: str) -> str:
    if focus == "announcement":
        scope = (
            "招标公告与投标人须知前附表：招标文件获取起止、提问/澄清截止、踏勘现场、"
            "投标预备会、投标截止、开标、投标有效期、计划工期、计划开工、计划完工。"
        )
        duration_schema = (
            ',\n"duration": {"days": 218, "start_date": "2023-11-25", '
            '"completion_date": "2024-06-30", "page": 14}'
        )
    elif focus == "contract":
        scope = (
            "评标与合同授予部分：开标/评标时间、中标通知、履约担保、签订合同、"
            "退还投标保证金、缺陷责任期等时间要求。"
        )
        duration_schema = ""
    else:
        scope = (
            "保证金与缺陷责任条款：投标保证金退还期限、质量保证金（保留金）返还期限、"
            "缺陷责任期/工程质量保修期的期限、起算与延长。"
        )
        duration_schema = ""

    return f"""任务：抽取招标文件中的关键时间节点。本次只负责：{scope}
只输出 JSON：
{{"key_dates": [
  {{"event": "招标文件获取开始", "datetime": "2023-10-24 10:00", "page": 11, "quote": "..."}}
]{duration_schema}}}
要求：
- 只抽取明确出现的时间节点，不要复制整段条款；quote 不超过 40 字。
- datetime 保留原文精度（YYYY-MM-DD HH:MM）；只有日期就写日期；原文是“自...起 N 天”的保留原文并给出可计算说明。
- 原文未明确或选项无法判断的，datetime 填 null 并保留 quote。
- 不要输出不在本次负责范围内的事件。
- page 使用 [PDF p.X] 中的 X。
原文：
{context}"""


def _normalize_event(name: object) -> str:
    return re.sub(r"(时间|日期)$", "", str(name or "")).strip()


def _fill_missing_dates(dates: list[dict], overview: dict | None) -> list[dict]:
    if overview:
        fields = overview.get("fields") or []
        has_validity = any(
            item.get("datetime") and "投标有效期" in str(item.get("event") or "")
            for item in dates
        )
        if not has_validity:
            field = next(
                (
                    item
                    for item in fields
                    if item.get("name") == "投标有效期" and item.get("value")
                ),
                None,
            )
            if field:
                dates.append(
                    {
                        "event": "投标有效期",
                        "datetime": field.get("value"),
                        "page": field.get("page"),
                        "quote": "来自项目概况字段",
                    }
                )
    non_null = {_normalize_event(item.get("event")) for item in dates if item.get("datetime")}

    def is_duplicate(item: dict) -> bool:
        if item.get("datetime"):
            return False
        name = _normalize_event(item.get("event"))
        return any(candidate and candidate in name for candidate in non_null)

    return [item for item in dates if not is_duplicate(item)]


def _extract_key_dates(
    client: DeepSeekExtractor, blocks: list[dict], overview: dict | None
) -> dict:
    context_a = "\n\n".join([render_pages(blocks, 9, 16), render_pages(blocks, 31, 33)])
    print("[extract] key_dates 1/3（公告/前附表）…", flush=True)
    part_a = client.json_call(
        _key_dates_prompt(context_a, "announcement"), max_tokens=8000
    )

    context_b = render_pages(blocks, 40, 46)
    print("[extract] key_dates 2/3（评标/合同授予）…", flush=True)
    part_b = client.json_call(
        _key_dates_prompt(context_b, "contract"), max_tokens=8000
    )

    context_c = "\n\n".join([
        render_pages(blocks, 36, 39),
        render_pages(blocks, 126, 131),
        render_pages(blocks, 141, 141),
    ])
    print("[extract] key_dates 3/3（保证金/缺陷责任期）…", flush=True)
    part_c = client.json_call(
        _key_dates_prompt(context_c, "guarantee"), max_tokens=6000
    )

    dates = (
        (part_a.get("key_dates") or [])
        + (part_b.get("key_dates") or [])
        + (part_c.get("key_dates") or [])
    )
    dates = _fill_missing_dates(dates, overview)
    return {
        "key_dates": _merge_items(dates, ("event", "datetime")),
        "duration": part_a.get("duration") or part_b.get("duration"),
    }


# ---------- Markdown 输出 ----------

def _cell(value: object) -> str:
    if value is None:
        return "—"
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_markdown(result: dict) -> str:
    lines: list[str] = [
        "# 招标文件结构化抽取结果",
        "",
        f"- 来源：{result.get('source', '')}",
        f"- doc_id：{result.get('doc_id', '')}",
        f"- 生成时间：{result.get('generated_at', '')}",
        "",
    ]

    toc = result.get("toc") or []
    if toc:
        lines += ["## 目录（自动解析）", "", "| 标题 | 印刷页 | 层级 |", "|---|---|---|"]
        for entry in toc:
            lines.append(
                f"| {_cell(entry.get('title'))} | "
                f"{_cell(entry.get('printed_page'))} | {_cell(entry.get('level'))} |"
            )
        lines.append("")

    lines += [
        "## 一、项目概况",
        "",
        "| 字段 | 内容 | PDF页 |",
        "|---|---|---|",
    ]
    overview = (result.get("project_overview") or {}).get("fields") or []
    for field in overview:
        lines.append(
            f"| {_cell(field.get('name'))} | {_cell(field.get('value'))} | "
            f"{_cell(field.get('page'))} |"
        )

    evaluation = result.get("evaluation") or {}
    lines += [
        "",
        "## 二、评标办法",
        "",
        f"- 评标方法：{_cell(evaluation.get('method'))}",
        f"- 总分：{_cell(evaluation.get('total_points'))}",
        "",
        "### 分值构成",
        "",
        "| 评审项 | 分值 | PDF页 |",
        "|---|---|---|",
    ]
    for item in evaluation.get("points_breakdown") or []:
        lines.append(
            f"| {_cell(item.get('item'))} | {_cell(item.get('points'))} | "
            f"{_cell(item.get('page'))} |"
        )

    lines += ["", "### 初步评审标准", "", "| 类别 | 评审因素 | 评审标准 | PDF页 |", "|---|---|---|---|"]
    for item in evaluation.get("preliminary_review") or []:
        lines.append(
            f"| {_cell(item.get('category'))} | {_cell(item.get('item'))} | "
            f"{_cell(item.get('standard'))} | {_cell(item.get('page'))} |"
        )

    lines += ["", "### 评分标准（全量）", "", "| 类别 | 评分因素 | 子项 | 分值 | 评分标准 | PDF页 |", "|---|---|---|---|---|---|"]
    factors = evaluation.get("scoring_factors") or []
    for item in factors:
        lines.append(
            f"| {_cell(item.get('category'))} | {_cell(item.get('item'))} | "
            f"{_cell(item.get('sub_item'))} | {_cell(item.get('points'))} | "
            f"{_cell(item.get('standard'))} | {_cell(item.get('page'))} |"
        )

    breakdown = {
        str(item.get("item")): item.get("points")
        for item in evaluation.get("points_breakdown") or []
    }
    category_totals: dict[str, float] = defaultdict(float)
    no_points: list[str] = []
    for item in factors:
        category = str(item.get("category") or "")
        try:
            category_totals[category] += float(item.get("points"))
        except (TypeError, ValueError):
            no_points.append(str(item.get("item") or ""))
    for category, total in category_totals.items():
        try:
            expected = float(breakdown.get(category))
        except (TypeError, ValueError):
            continue
        if abs(total - expected) > 0.01:
            lines.append(
                f"- 分值校验：{category} 评分项逐项合计 {total:g} 分，与分值构成 "
                f"{expected:g} 分不一致；若存在父项与子项并列（如“资源配置计划”6 分与 "
                "7.1–7.3 各 2 分），统计时请勿重复计入。"
            )
    if no_points:
        lines.append(
            f"- 分值校验：{'、'.join(no_points)}为无分值汇总行，以有分值的明细行为准。"
        )

    price = evaluation.get("price_scoring") or {}
    lines += [
        "",
        "### 报价评分规则",
        "",
        f"- 评标基准价：{_cell(price.get('base_price_rule'))}",
        f"- 偏差率：{_cell(price.get('deviation_rule'))}",
        f"- 扣分规则：{_cell(price.get('deduction_rule'))}",
        f"- 中小企业优惠：{_cell(price.get('small_enterprise_rule'))}",
        f"- 最终得分：{_cell(evaluation.get('final_score_rule'))}",
        "",
        "### 否决投标情形",
        "",
    ]
    for item in evaluation.get("veto_conditions") or []:
        lines.append(f"- {_cell(item.get('condition'))}（PDF p.{_cell(item.get('page'))}）")

    appendix_items = (result.get("instructions_appendix") or {}).get("items") or []
    lines += [
        "",
        "## 三、投标人须知前附表（全量）",
        "",
        "| 条款号 | 条款名称 | 编列内容 | PDF页 |",
        "|---|---|---|---|",
    ]
    for item in appendix_items:
        lines.append(
            f"| {_cell(item.get('clause'))} | {_cell(item.get('item'))} | "
            f"{_cell(item.get('content'))} | {_cell(item.get('page'))} |"
        )
    suspicious = [
        str(item.get("clause"))
        for item in appendix_items
        if str(item.get("content") or "").lstrip().startswith(
            ("ditbj", "http", "www", "）", ")")
        )
    ]
    if suspicious:
        lines.append(
            f"- 注：条款 {'、'.join(suspicious)} 在原表格跨页处被拆分，"
            "前附表行内容可能不完整，请以“四、资格审查条件”中的完整表述为准。"
        )

    qualification = result.get("qualification") or {}
    lines += [
        "",
        "## 四、资格审查条件",
        "",
        f"- 审查方式：{_cell(qualification.get('review_method'))}",
        "",
        "| 类别 | 要求 | PDF页 |",
        "|---|---|---|",
    ]
    for item in qualification.get("conditions") or []:
        lines.append(
            f"| {_cell(item.get('category'))} | {_cell(item.get('requirement'))} | "
            f"{_cell(item.get('page'))} |"
        )
    lines += ["", "### 需提交的证明材料", "", "| 材料 | 要求 | PDF页 |", "|---|---|---|"]
    for item in qualification.get("required_documents") or []:
        lines.append(
            f"| {_cell(item.get('document'))} | {_cell(item.get('requirement'))} | "
            f"{_cell(item.get('page'))} |"
        )

    bid_format = result.get("bid_format") or {}
    lines += ["", "## 五、第八章 投标文件格式清单", ""]
    for item in bid_format.get("items") or []:
        page = item.get("page")
        suffix = f"（PDF p.{page}）" if page else "（目录项，正文未检测到独立页面）"
        lines.append(f"- {_cell(item.get('no'))}、{_cell(item.get('title'))}{suffix}")
        for sub in item.get("sub_items") or []:
            sub_page = f"（PDF p.{sub.get('page')}）" if sub.get("page") else ""
            lines.append(f"  - {_cell(sub.get('title'))}{sub_page}")
    for note in bid_format.get("notes") or []:
        lines.append(f"- 备注：{_cell(note)}")

    lines += ["", "## 六、关键时间节点", "", "| 事项 | 时间 | PDF页 |", "|---|---|---|"]
    for item in result.get("key_dates") or []:
        lines.append(
            f"| {_cell(item.get('event'))} | {_cell(item.get('datetime'))} | "
            f"{_cell(item.get('page'))} |"
        )
    duration = result.get("duration") or {}
    if duration:
        lines += [
            "",
            f"- 工期：{_cell(duration.get('days'))} 天；"
            f"计划开工 {_cell(duration.get('start_date'))}；"
            f"计划完工 {_cell(duration.get('completion_date'))}"
            f"（PDF p.{_cell(duration.get('page'))}）",
        ]

    warnings = result.get("provenance_warnings")
    if warnings is not None:
        lines += ["", "## 七、溯源核对", ""]
        if warnings:
            for warning in warnings:
                lines.append(
                    f"- {_cell(warning.get('section'))} / {_cell(warning.get('item'))}："
                    f"{_cell(warning.get('issue'))}（PDF p.{_cell(warning.get('page'))}）"
                )
        else:
            lines.append("- 所有带页码的抽取项均通过页码存在性与原文引用校验。")

    return "\n".join(lines).rstrip() + "\n"


def _extract_appendix(client: DeepSeekExtractor, blocks: list[dict]) -> dict:
    context = render_pages(blocks, 13, 30)
    parts = split_context(context, 3500)
    items: list[dict] = []
    for index, part in enumerate(parts, start=1):
        print(f"[extract] instructions_appendix {index}/{len(parts)} …", flush=True)
        payload = client.extract_section(
            "instructions_appendix", _appendix_prompt(part), max_tokens=6000
        )
        items.extend(payload.get("items") or [])
    return {"items": _merge_items(items, ("clause", "item"))}


def _extract_evaluation(client: DeepSeekExtractor, blocks: list[dict]) -> dict:
    print("[extract] evaluation 1/3（初步评审/分值/报价/否决情形）…", flush=True)
    base = client.extract_section(
        "evaluation", _evaluation_base_prompt(blocks), max_tokens=6000
    )
    factors: list[dict] = []
    ranges = [(79, 83), (84, 88)]
    for index, (start, end) in enumerate(ranges, start=2):
        print(f"[extract] evaluation {index}/3（评分标准 p{start}-{end}）…", flush=True)
        payload = client.extract_section(
            "evaluation",
            _evaluation_scoring_prompt(blocks, start, end),
            max_tokens=7000,
        )
        factors.extend(payload.get("scoring_factors") or [])
    base["scoring_factors"] = _merge_items(
        factors, ("category", "item", "sub_item")
    )
    return base


def _cache_load(path: Path) -> dict | list | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _cache_save(path: Path, value: dict | list) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


@traceable(name="extract.document", run_type="chain")
def extract_document(
    pdf_path: Path,
    settings: Settings,
    output_dir: Path | None = None,
    refresh: bool = False,
) -> tuple[Path, Path, dict]:
    pdf_path = pdf_path.resolve()
    if not pdf_path.exists():
        raise FileNotFoundError(f"文件不存在: {pdf_path}")

    doc_id, doc_dir, blocks = load_blocks_for_pdf(pdf_path, settings)
    toc_entries = toc_from_blocks(blocks)
    target_dir = output_dir or doc_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    parts_dir = target_dir / "extraction_parts"
    parts_dir.mkdir(parents=True, exist_ok=True)
    client = DeepSeekExtractor(settings)

    def cached(name: str, loader) -> dict | list:
        path = parts_dir / f"{name}.json"
        if not refresh:
            value = _cache_load(path)
            if value is not None:
                print(f"[extract] {name} 复用缓存", flush=True)
                return value
        print(f"[extract] {name} …", flush=True)
        value = loader()
        _cache_save(path, value)
        return value

    overview = cached(
        "project_overview",
        lambda: client.extract_section(
            "project_overview", _overview_prompt(blocks), max_tokens=5000
        ),
    )
    appendix = cached(
        "instructions_appendix", lambda: _extract_appendix(client, blocks)
    )
    evaluation = cached("evaluation", lambda: _extract_evaluation(client, blocks))
    qualification = cached(
        "qualification",
        lambda: client.extract_section(
            "qualification", _qualification_prompt(blocks), max_tokens=6000
        ),
    )
    bid_format = cached(
        "bid_format",
        lambda: client.extract_section(
            "bid_format", _bid_format_prompt(blocks), max_tokens=5000
        ),
    )
    key_dates = cached(
        "key_dates", lambda: _extract_key_dates(client, blocks, overview)
    )

    result: dict = {
        "doc_id": doc_id,
        "source": pdf_path.name,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "llm": {"provider": settings.llm_provider, "model": settings.deepseek_model},
        "toc": [asdict(entry) for entry in toc_entries],
        "project_overview": overview,
        "instructions_appendix": appendix,
        "evaluation": evaluation,
        "qualification": qualification,
        "bid_format": bid_format,
        "key_dates": key_dates.get("key_dates") if isinstance(key_dates, dict) else [],
        "duration": key_dates.get("duration") if isinstance(key_dates, dict) else None,
    }
    result["provenance_warnings"] = check_provenance(result, blocks)
    print(f"[verify] 溯源核对警告: {len(result['provenance_warnings'])} 条", flush=True)

    json_path = target_dir / "extraction.json"
    md_path = target_dir / "extraction.md"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(result), encoding="utf-8")
    print(f"[done] JSON: {json_path}", flush=True)
    print(f"[done] Markdown: {md_path}", flush=True)
    return json_path, md_path, result
