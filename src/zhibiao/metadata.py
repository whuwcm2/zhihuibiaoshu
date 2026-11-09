from __future__ import annotations

from typing import Any

QUALIFICATION_TAG = "资格审查"
FORMULA_TAG = "计算公式"
SECTION_TAG = "章节写法"

QUALIFICATION_KEYWORDS = (
    "资格审查",
    "资格要求",
    "资格材料",
    "投标人资格",
    "资质",
    "营业执照",
    "安全生产许可证",
    "业绩",
    "财务",
    "信用",
    "证书",
)
FORMULA_KEYWORDS = (
    "公式",
    "计算",
    "费率",
    "定额",
    "工程量",
    "计价",
    "折算",
    "评分计算",
)
SECTION_KEYWORDS = (
    "施工组织设计",
    "章节",
    "编制",
    "写法",
    "方案",
    "措施",
    "格式",
    "目录",
    "技术标",
    "商务标",
)


def infer_tags(text: str, heading: str = "") -> list[str]:
    haystack = f"{heading}\n{text}"
    tags: list[str] = []
    if any(keyword in haystack for keyword in QUALIFICATION_KEYWORDS):
        tags.append(QUALIFICATION_TAG)
    if any(keyword in haystack for keyword in FORMULA_KEYWORDS):
        tags.append(FORMULA_TAG)
    if any(keyword in haystack for keyword in SECTION_KEYWORDS):
        tags.append(SECTION_TAG)
    return tags


def chunk_metadata(
    text: str,
    heading: str,
    block_types: str,
    table_id: str = "",
) -> dict[str, Any]:
    is_table = bool(table_id) or "table" in block_types
    tags = infer_tags(text, heading)
    return {
        "type": "table" if is_table else "text",
        "table_id": table_id if is_table else "",
        "tags": ",".join(tags),
        "qualification": QUALIFICATION_TAG in tags,
    }


def normalize_metadata(
    chunk_id: str, text: str, metadata: dict[str, Any] | None
) -> dict[str, Any]:
    """兼容旧 collection：缺少 type/table_id/tags 时按块内容推断。"""
    result = dict(metadata or {})
    heading = str(result.get("heading") or "")
    block_types = str(result.get("block_types") or "")
    table_id = str(result.get("table_id") or "")
    tags_value = result.get("tags")
    if isinstance(tags_value, list):
        tags = [str(tag) for tag in tags_value if tag]
    else:
        tags = [tag for tag in str(tags_value or "").split(",") if tag]
    if not tags:
        tags = infer_tags(text, heading)

    is_table = (
        str(result.get("type") or "").lower() == "table"
        or "table" in block_types
        or bool(table_id)
    )
    if is_table and not table_id:
        table_id = f"legacy-{chunk_id}"

    result["type"] = "table" if is_table else "text"
    result["table_id"] = table_id if is_table else ""
    result["tags"] = ",".join(tags)
    result["qualification"] = bool(result.get("qualification")) or (
        QUALIFICATION_TAG in tags
    )
    return result
