from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

PLACEHOLDER = "【待填写】"

PROFILE_TEMPLATE: dict[str, Any] = {
    "company_name": PLACEHOLDER,
    "legal_representative": PLACEHOLDER,
    "registered_address": PLACEHOLDER,
    "contact_person": PLACEHOLDER,
    "contact_phone": PLACEHOLDER,
    "email": PLACEHOLDER,
    "business_license_no": PLACEHOLDER,
    "registered_capital": PLACEHOLDER,
    "established_date": PLACEHOLDER,
    "qualification": {
        "name": PLACEHOLDER,
        "grade": PLACEHOLDER,
        "certificate_no": PLACEHOLDER,
        "valid_until": PLACEHOLDER,
    },
    "safety_license": {
        "certificate_no": PLACEHOLDER,
        "valid_until": PLACEHOLDER,
    },
    "similar_projects": [
        {
            "project_name": PLACEHOLDER,
            "owner": PLACEHOLDER,
            "amount": PLACEHOLDER,
            "start_date": PLACEHOLDER,
            "end_date": PLACEHOLDER,
            "role": PLACEHOLDER,
            "certificate": PLACEHOLDER,
        }
    ],
    "personnel": {
        "project_manager": {
            "name": PLACEHOLDER,
            "certificate": PLACEHOLDER,
            "title": PLACEHOLDER,
            "phone": PLACEHOLDER,
        },
        "technical_lead": {
            "name": PLACEHOLDER,
            "certificate": PLACEHOLDER,
            "title": PLACEHOLDER,
        },
        "quality_manager": {
            "name": PLACEHOLDER,
            "certificate": PLACEHOLDER,
            "title": PLACEHOLDER,
        },
        "safety_manager": {
            "name": PLACEHOLDER,
            "certificate": PLACEHOLDER,
            "title": PLACEHOLDER,
        },
    },
    "financial": {
        "years": [PLACEHOLDER, PLACEHOLDER, PLACEHOLDER],
        "revenue": [PLACEHOLDER, PLACEHOLDER, PLACEHOLDER],
        "net_profit": [PLACEHOLDER, PLACEHOLDER, PLACEHOLDER],
        "audit_agency": PLACEHOLDER,
    },
    "credit": {
        "rating": PLACEHOLDER,
        "certificates": [PLACEHOLDER],
    },
    "management_systems": [PLACEHOLDER],
    "bid_bond": {
        "method": PLACEHOLDER,
        "amount": PLACEHOLDER,
        "valid_until": PLACEHOLDER,
    },
    "other": {},
}


def _deep_merge(default: Any, value: Any) -> Any:
    if isinstance(default, dict) and isinstance(value, dict):
        merged = {key: copy.deepcopy(item) for key, item in default.items()}
        for key, item in value.items():
            if key in default:
                merged[key] = _deep_merge(default[key], item)
            else:
                merged[key] = copy.deepcopy(item)
        return merged
    if isinstance(default, list) and isinstance(value, list):
        if not value:
            return copy.deepcopy(default)
        if default and isinstance(default[0], dict):
            return [_deep_merge(default[0], item) for item in value]
        return copy.deepcopy(value)
    if value is None or value == "":
        return copy.deepcopy(default)
    return copy.deepcopy(value)


def _replace_empty(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _replace_empty(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_empty(item) for item in value] or [PLACEHOLDER]
    if value is None or value == "":
        return PLACEHOLDER
    return value


def normalize_profile(raw: dict[str, Any] | None) -> dict[str, Any]:
    """模板深合并 + 空值替换为【待填写】，确保下游永远不会拿到空字段。"""
    return _replace_empty(_deep_merge(PROFILE_TEMPLATE, raw or {}))


def load_profile(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        if path is not None:
            print(
                f"[warn] 未找到投标人资料文件 {path}，全部字段将使用【待填写】占位",
                flush=True,
            )
        return normalize_profile({})
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("bidder_profile.json 顶层必须是 JSON 对象")
    return normalize_profile(raw)


def missing_fields(profile: dict[str, Any], prefix: str = "") -> list[str]:
    """返回所有仍为【待填写】的字段路径，供审查 Agent 使用。"""
    missing: list[str] = []
    if isinstance(profile, dict):
        for key, value in profile.items():
            path = f"{prefix}.{key}" if prefix else key
            if isinstance(value, (dict, list)):
                missing.extend(missing_fields(value, path))
            elif value == PLACEHOLDER:
                missing.append(path)
    elif isinstance(profile, list):
        for index, value in enumerate(profile):
            path = f"{prefix}[{index}]"
            if isinstance(value, (dict, list)):
                missing.extend(missing_fields(value, path))
            elif value == PLACEHOLDER:
                missing.append(path)
    return missing


def profile_json(profile: dict[str, Any]) -> str:
    return json.dumps(profile, ensure_ascii=False, indent=2)
