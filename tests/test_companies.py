from __future__ import annotations

import uuid
from types import SimpleNamespace

from api import routes


def test_company_crud(db_client):
    created = db_client.post(
        "/api/companies",
        json={
            "company_name": "  测试工程有限公司  ",
            "profile": {
                "legal_representative": "张三",
                "contact_person": "李四",
                "contact_phone": "13800000000",
            },
        },
    )
    assert created.status_code == 201
    company = created.json()
    company_id = company["id"]
    assert company["company_name"] == "测试工程有限公司"
    assert company["contact_person"] == "李四"
    assert company["contact_phone"] == "13800000000"
    assert company["profile"]["company_name"] == "测试工程有限公司"

    listed = db_client.get("/api/companies")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [company_id]

    found = db_client.get("/api/companies", params={"q": "测试"})
    assert [item["id"] for item in found.json()] == [company_id]

    detail = db_client.get(f"/api/companies/{company_id}")
    assert detail.status_code == 200
    assert detail.json()["profile"]["legal_representative"] == "张三"

    updated = db_client.put(
        f"/api/companies/{company_id}",
        json={
            "company_name": "测试工程有限公司（更新）",
            "profile": {"contact_person": "王五"},
        },
    )
    assert updated.status_code == 200
    assert updated.json()["company_name"] == "测试工程有限公司（更新）"
    assert updated.json()["contact_person"] == "王五"

    deleted = db_client.delete(f"/api/companies/{company_id}")
    assert deleted.status_code == 204
    assert db_client.get(f"/api/companies/{company_id}").status_code == 404


def test_company_name_validation_and_duplicate(db_client):
    blank = db_client.post(
        "/api/companies", json={"company_name": "  ", "profile": {}}
    )
    assert blank.status_code == 422

    first = db_client.post(
        "/api/companies", json={"company_name": "重复公司", "profile": {}}
    )
    assert first.status_code == 201

    duplicate = db_client.post(
        "/api/companies", json={"company_name": "重复公司", "profile": {}}
    )
    assert duplicate.status_code == 409
    assert "已存在" in duplicate.json()["detail"]


def test_bid_uses_company_profile(db_client, settings, monkeypatch):
    parsed_dir = settings.data_dir / "parsed" / "doc-1"
    parsed_dir.mkdir(parents=True)
    (parsed_dir / "extraction.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(routes, "get_settings", lambda: settings)

    company = db_client.post(
        "/api/companies",
        json={
            "company_name": "投标公司",
            "profile": {"legal_representative": "赵六"},
        },
    ).json()

    captured = {}

    def fake_apply_async(args, task_id=None):
        captured.update(args=args, task_id=task_id)
        return SimpleNamespace(id=task_id)

    monkeypatch.setattr(
        routes, "write_bid_task", SimpleNamespace(apply_async=fake_apply_async)
    )

    response = db_client.post(
        "/api/bids",
        json={"doc_id": "doc-1", "company_id": company["id"], "export_docx": False},
    )

    assert response.status_code == 202
    assert captured["args"][2]["company_name"] == "投标公司"
    assert captured["args"][2]["legal_representative"] == "赵六"
    assert captured["args"][3] is False


def test_bid_rejects_profile_and_company_id_together(db_client):
    response = db_client.post(
        "/api/bids",
        json={
            "doc_id": "doc-1",
            "company_id": str(uuid.uuid4()),
            "profile": {"company_name": "测试公司"},
        },
    )
    assert response.status_code == 422


def test_bid_with_unknown_company_returns_404(db_client, settings, monkeypatch):
    parsed_dir = settings.data_dir / "parsed" / "doc-2"
    parsed_dir.mkdir(parents=True)
    (parsed_dir / "extraction.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(routes, "get_settings", lambda: settings)

    response = db_client.post(
        "/api/bids",
        json={"doc_id": "doc-2", "company_id": str(uuid.uuid4())},
    )

    assert response.status_code == 404
    assert "公司信息不存在" in response.json()["detail"]
