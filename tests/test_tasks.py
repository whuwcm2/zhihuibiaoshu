from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from zhibiao.tasks import celery_app, parse_pdf_task, write_bid_task


@pytest.fixture(autouse=True)
def no_task_database(monkeypatch):
    monkeypatch.setattr(
        "zhibiao.tasks.get_settings",
        lambda: SimpleNamespace(database_url=""),
    )


def test_celery_configuration():
    assert celery_app.conf.task_serializer == "json"
    assert celery_app.conf.result_serializer == "json"
    assert celery_app.conf.task_track_started is True
    assert celery_app.conf.broker_transport_options == {"visibility_timeout": 7200}
    assert "zhibiao.parse_pdf" in celery_app.tasks
    assert "bidding.write_bid" in celery_app.tasks


def test_parse_pdf_task_wraps_service(monkeypatch):
    monkeypatch.setattr(
        "zhibiao.tasks.parse_pdf_to_chunks",
        lambda *args, **kwargs: {
            "doc_id": "doc-1",
            "filename": kwargs.get("filename"),
        },
    )
    monkeypatch.setattr(parse_pdf_task, "update_state", lambda *args, **kwargs: None)

    result = parse_pdf_task.run("job-1", "x.pdf", "original.pdf", "pymupdf")

    assert result["job_id"] == "job-1"
    assert result["doc_id"] == "doc-1"
    assert result["filename"] == "original.pdf"
    assert "started_at" in result
    assert "finished_at" in result


def test_parse_pdf_task_extract_and_ingest(monkeypatch):
    monkeypatch.setattr(
        "zhibiao.tasks.parse_pdf_to_chunks",
        lambda *args, **kwargs: {"doc_id": "doc-1", "filename": "x.pdf"},
    )
    monkeypatch.setattr("zhibiao.tasks.get_settings", lambda: object())
    monkeypatch.setattr(parse_pdf_task, "update_state", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "zhibiao.extractor.extract_document",
        lambda *args, **kwargs: (
            Path("extraction.json"),
            Path("extraction.md"),
            {
                "project_overview": {
                    "fields": [{"name": "项目名称", "value": "测试项目"}]
                },
                "toc": [1],
                "evaluation": {"scoring_factors": [1, 2]},
            },
        ),
    )
    monkeypatch.setattr("zhibiao.pipeline.ingest_pdf", lambda *args, **kwargs: None)

    result = parse_pdf_task.run("job-1", "x.pdf", "x.pdf", "auto", True, True)

    assert result["extraction_path"] == "extraction.json"
    assert result["extraction_summary"]["project_name"] == "测试项目"
    assert result["extraction_summary"]["scoring_factor_count"] == 2
    assert result["ingested"] is True
    assert "finished_at" in result


def test_write_bid_task_wraps_service(monkeypatch):
    monkeypatch.setattr(
        "zhibiao.tasks.write_bid",
        lambda *args, **kwargs: {
            "output_dir": Path("out"),
            "markdown_path": Path("bid.md"),
            "docx_path": Path("bid.docx"),
            "agent_dir": Path("agent_outputs"),
            "placeholder_count": 3,
            "review": {"summary": "ok"},
            "scoring_report": {"items": [], "total_points": 0},
        },
    )
    monkeypatch.setattr(write_bid_task, "update_state", lambda *args, **kwargs: None)

    result = write_bid_task.run(
        "job-1", "doc-1", {"company_name": "测试公司"}, True
    )

    assert result["job_id"] == "job-1"
    assert result["doc_id"] == "doc-1"
    assert result["markdown_path"] == "bid.md"
    assert result["docx_path"] == "bid.docx"
    assert result["placeholder_count"] == 3
    assert result["review"]["summary"] == "ok"
    assert result["scoring_report"]["total_points"] == 0
    assert "started_at" in result
    assert "finished_at" in result
