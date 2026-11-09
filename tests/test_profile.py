from __future__ import annotations

from zhibiao.profile import PLACEHOLDER, load_profile, missing_fields, normalize_profile


def test_normalize_profile_fills_missing_fields():
    profile = normalize_profile(
        {"company_name": "示例公司", "qualification": {"grade": "一级"}}
    )

    assert profile["company_name"] == "示例公司"
    assert profile["qualification"]["grade"] == "一级"
    assert profile["qualification"]["name"] == PLACEHOLDER
    assert profile["similar_projects"][0]["project_name"] == PLACEHOLDER
    assert profile["financial"]["years"] == [PLACEHOLDER, PLACEHOLDER, PLACEHOLDER]
    assert "company_name" not in missing_fields(profile)
    assert "qualification.name" in missing_fields(profile)


def test_normalize_profile_merges_project_items():
    profile = normalize_profile(
        {"similar_projects": [{"project_name": "项目A", "owner": "业主A"}]}
    )

    assert profile["similar_projects"][0]["project_name"] == "项目A"
    assert profile["similar_projects"][0]["owner"] == "业主A"
    assert profile["similar_projects"][0]["amount"] == PLACEHOLDER


def test_load_profile_missing_file_uses_placeholders(tmp_path, capsys):
    profile = load_profile(tmp_path / "missing.json")

    assert profile["company_name"] == PLACEHOLDER
    assert "未找到投标人资料文件" in capsys.readouterr().out
