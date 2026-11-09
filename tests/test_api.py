from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from api import routes
from zhibiao import document_store, task_store
from zhibiao.db_models import Project


@pytest.fixture(autouse=True)
def redis_ok(monkeypatch):
    monkeypatch.setattr(routes, "_redis_ok", lambda: True)


def _create_task(
    db_run,
    job_id: str,
    task_type: str = "parse_pdf",
    payload: dict | None = None,
    doc_id: str | None = None,
):
    async def operation(session):
        return await task_store.create_task(
            session,
            job_id,
            task_type,
            payload=payload or {},
            doc_id=doc_id,
        )

    return db_run(operation)


def test_health(db_client):
    response = db_client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "zhibiao-api",
        "redis": True,
    }


def test_rejects_non_pdf_extension(db_client):
    response = db_client.post(
        "/api/parse", files={"file": ("note.txt", b"hello", "text/plain")}
    )

    assert response.status_code == 400
    assert ".pdf" in response.json()["detail"]


def test_rejects_invalid_pdf_magic(db_client):
    response = db_client.post(
        "/api/parse", files={"file": ("fake.pdf", b"not a pdf", "application/pdf")}
    )

    assert response.status_code == 400
    assert "有效的 PDF" in response.json()["detail"]


def test_parse_job_dispatches_and_reports_success(db_client, db_run, monkeypatch):
    captured = {}

    def fake_apply_async(args, task_id=None):
        captured.update(args=args, task_id=task_id)
        return SimpleNamespace(id=task_id)

    monkeypatch.setattr(
        routes, "parse_pdf_task", SimpleNamespace(apply_async=fake_apply_async)
    )

    response = db_client.post(
        "/api/parse",
        files={"file": ("doc.pdf", b"%PDF-1.4 test", "application/pdf")},
        data={"parser": "pymupdf", "extract": "true", "ingest": "true"},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending"
    assert body["status_url"] == f"/api/parse/{body['job_id']}"
    assert captured["task_id"] == body["job_id"]
    assert captured["args"][0] == body["job_id"]
    assert captured["args"][2:4] == ["doc.pdf", "pymupdf"]
    assert captured["args"][4:] == [True, True]
    expected_name = hashlib.sha1(b"%PDF-1.4 test").hexdigest()[:12] + "_doc.pdf"
    assert captured["args"][1].endswith(expected_name)

    result_payload = {
        "doc_id": "doc-1",
        "filename": "doc.pdf",
        "page_count": 2,
        "parser": "pymupdf",
        "block_count": 3,
        "chunk_count": 2,
        "markdown_path": "full.md",
        "chunks_path": "chunks.jsonl",
        "chunks_preview": [],
        "job_id": body["job_id"],
    }

    async def finish(session):
        await task_store.start_task(session, body["job_id"], stage="parsing")
        await task_store.finish_task(
            session,
            body["job_id"],
            "succeeded",
            result=result_payload,
            doc_id="doc-1",
        )

    db_run(finish)

    status = db_client.get(f"/api/parse/{body['job_id']}")
    assert status.status_code == 200
    status_body = status.json()
    assert status_body["status"] == "succeeded"
    assert status_body["filename"] == "doc.pdf"
    assert status_body["result"]["doc_id"] == "doc-1"
    assert status_body["result"]["chunk_count"] == 2
    assert status_body["started_at"] is not None
    assert status_body["finished_at"] is not None


def test_job_status_mapping(db_client, db_run):
    _create_task(db_run, "job-1", payload={"filename": "a.pdf"})

    pending = db_client.get("/api/parse/job-1").json()
    assert pending["status"] == "pending"
    assert pending["filename"] == "a.pdf"

    async def start(session):
        await task_store.start_task(session, "job-1", stage="parsing")

    db_run(start)
    running = db_client.get("/api/parse/job-1").json()
    assert running["status"] == "running"
    assert running["stage"] == "parsing"
    assert running["started_at"] is not None

    async def fail(session):
        await task_store.finish_task(
            session, "job-1", "failed", error="boom"
        )

    db_run(fail)
    failed = db_client.get("/api/parse/job-1").json()
    assert failed["status"] == "failed"
    assert failed["error"] == "boom"


def test_unknown_job_returns_404(db_client):
    response = db_client.get("/api/parse/not-a-job")

    assert response.status_code == 404


def test_create_bid_job_dispatches_and_reports_success(
    db_client, db_run, settings, monkeypatch
):
    parsed_dir = settings.data_dir / "parsed" / "doc-1"
    parsed_dir.mkdir(parents=True)
    (parsed_dir / "extraction.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(routes, "get_settings", lambda: settings)

    captured = {}

    def fake_apply_async(args, task_id=None):
        captured.update(args=args, task_id=task_id)
        return SimpleNamespace(id=task_id)

    monkeypatch.setattr(
        routes, "write_bid_task", SimpleNamespace(apply_async=fake_apply_async)
    )

    response = db_client.post(
        "/api/bids",
        json={
            "doc_id": "doc-1",
            "profile": {"company_name": "测试公司"},
            "export_docx": True,
        },
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending"
    assert body["doc_id"] == "doc-1"
    assert body["status_url"] == f"/api/bids/{body['job_id']}"
    assert captured["task_id"] == body["job_id"]
    assert captured["args"][0] == body["job_id"]
    assert captured["args"][1] == "doc-1"
    assert captured["args"][2]["company_name"] == "测试公司"
    assert captured["args"][3] is True

    result_payload = {
        "job_id": body["job_id"],
        "doc_id": "doc-1",
        "output_dir": "out",
        "markdown_path": "bid.md",
        "docx_path": "bid.docx",
        "agent_dir": "agent_outputs",
        "placeholder_count": 5,
        "review": {"issues": [], "summary": "ok"},
        "scoring_report": {"items": [], "total_points": 0},
    }

    async def finish(session):
        await task_store.start_task(session, body["job_id"], stage="writing_bid")
        await task_store.finish_task(
            session,
            body["job_id"],
            "succeeded",
            result=result_payload,
            doc_id="doc-1",
        )

    db_run(finish)

    status = db_client.get(f"/api/bids/{body['job_id']}")
    assert status.status_code == 200
    status_body = status.json()
    assert status_body["status"] == "succeeded"
    assert status_body["doc_id"] == "doc-1"
    assert status_body["result"]["placeholder_count"] == 5
    assert status_body["result"]["review"]["summary"] == "ok"


def test_create_bid_job_missing_extraction_returns_404(
    db_client, settings, monkeypatch
):
    monkeypatch.setattr(routes, "get_settings", lambda: settings)

    response = db_client.post("/api/bids", json={"doc_id": "missing-doc"})

    assert response.status_code == 404
    assert "未找到" in response.json()["detail"]


def test_list_documents(db_client, db_run, settings):
    async def seed(session):
        project = Project(name="测试项目")
        session.add(project)
        await session.flush()
        await document_store.upsert_document(
            session,
            doc_id="doc-1",
            filename="tender.pdf",
            source="tender.pdf",
            root=str(settings.data_dir / "parsed"),
            page_count=10,
            parser="mineru",
            chunk_count=2,
            has_extraction=True,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            project_id=project.id,
        )

    db_run(seed)

    response = db_client.get("/api/documents")

    assert response.status_code == 200
    items = response.json()
    assert items[0]["doc_id"] == "doc-1"
    assert items[0]["project_name"] == "测试项目"
    assert items[0]["chunk_count"] == 2
    assert items[0]["has_extraction"] is True
    assert items[0]["created_at"].startswith("2026-01-01")


def test_list_bid_history_and_download(db_client, settings, monkeypatch):
    monkeypatch.setattr(routes, "get_settings", lambda: settings)
    bid_dir = settings.data_dir / "bids" / "doc-1"
    bid_dir.mkdir(parents=True)
    (bid_dir / "bid_meta.json").write_text(
        json.dumps(
            {
                "project_name": "测试项目",
                "company_name": "测试公司",
                "generated_at": "2026-01-01T00:00:00",
                "placeholder_count": 3,
                "review": {"summary": "ok"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (bid_dir / "bid.md").write_text("# 测试投标文件", encoding="utf-8")
    (bid_dir / "bid.docx").write_bytes(b"PK fake docx")

    response = db_client.get("/api/bids")
    assert response.status_code == 200
    items = response.json()
    assert items[0]["doc_id"] == "doc-1"
    assert items[0]["company_name"] == "测试公司"
    assert items[0]["has_docx"] is True

    preview = db_client.get("/api/bids/doc-1/files/bid.md?download=false")
    assert preview.status_code == 200
    assert "测试投标文件" in preview.text

    download = db_client.get("/api/bids/doc-1/files/bid.docx")
    assert download.status_code == 200
    assert db_client.get("/api/bids/doc-1/files/evil.txt").status_code == 404


def test_bid_status_mapping_and_kind_check(db_client, db_run):
    _create_task(db_run, "bid-job", "write_bid", {"doc_id": "doc-1"})
    _create_task(db_run, "parse-job", "parse_pdf", {"filename": "a.pdf"})

    async def start(session):
        await task_store.start_task(session, "bid-job", stage="reviewer")

    db_run(start)
    running = db_client.get("/api/bids/bid-job").json()
    assert running["status"] == "running"
    assert running["doc_id"] == "doc-1"
    assert running["stage"] == "reviewer"
    assert running["started_at"] is not None

    async def fail(session):
        await task_store.finish_task(
            session, "bid-job", "failed", error="boom"
        )

    db_run(fail)
    failed = db_client.get("/api/bids/bid-job").json()
    assert failed["status"] == "failed"
    assert failed["error"] == "boom"

    assert db_client.get("/api/bids/parse-job").status_code == 404
    assert db_client.get("/api/bids/not-a-job").status_code == 404


def test_task_history(db_client, db_run):
    _create_task(db_run, "parse-job", "parse_pdf", {"filename": "a.pdf"})
    _create_task(db_run, "bid-job", "write_bid", {"doc_id": "doc-1"})

    response = db_client.get("/api/tasks")
    assert response.status_code == 200
    ids = {item["id"] for item in response.json()}
    assert ids == {"parse-job", "bid-job"}

    filtered = db_client.get("/api/tasks", params={"task_type": "write_bid"})
    assert [item["id"] for item in filtered.json()] == ["bid-job"]


def test_search_endpoint(db_client, monkeypatch):
    class FakeRetriever:
        def __init__(self, settings):
            pass

        def search(self, query, n_results=5, intent=None):
            return {
                "query": query,
                "intent": intent or "formula",
                "strategy": {"forced_qualification": 0},
                "candidate_count": 4,
                "took_ms": 3,
                "results": [
                    {
                        "id": "doc:00001",
                        "doc_id": "doc-1",
                        "text": "投标报价计算公式",
                        "snippet": "投标报价计算公式",
                        "heading": "第五章 投标报价",
                        "page_start": 20,
                        "page_end": 20,
                        "source": "a.pdf",
                        "type": "table",
                        "table_id": "table-p20-001",
                        "tags": ["计算公式"],
                        "score": 0.95,
                        "keyword_score": 0.9,
                        "vector_score": 0.7,
                        "forced": False,
                        "reasons": ["bm25_table", "vector"],
                    }
                ],
            }

    monkeypatch.setattr(routes, "HybridRetriever", FakeRetriever)

    response = db_client.get(
        "/api/search", params={"q": "投标报价计算公式", "n_results": 2}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "formula"
    assert body["candidate_count"] == 4
    assert body["results"][0]["type"] == "table"
    assert body["results"][0]["table_id"] == "table-p20-001"


def test_search_endpoint_empty_index_returns_503(db_client, monkeypatch):
    class EmptyRetriever:
        def __init__(self, settings):
            pass

        def search(self, query, n_results=5, intent=None):
            raise RuntimeError("向量库为空，请先执行 ingest")

    monkeypatch.setattr(routes, "HybridRetriever", EmptyRetriever)

    response = db_client.get("/api/search", params={"q": "资格审查"})

    assert response.status_code == 503
    assert "向量库为空" in response.json()["detail"]
