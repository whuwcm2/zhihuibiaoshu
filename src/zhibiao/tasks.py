from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from celery import Celery
from langsmith import traceable

from . import document_store, task_store
from .bid_writer import write_bid
from .config import get_settings
from .pipeline import parse_pdf_to_chunks

settings = get_settings()

celery_app = Celery(
    "zhibiao",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    result_expires=86400,
    broker_connection_retry_on_startup=True,
    broker_transport_options={"visibility_timeout": 7200},
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    timezone="Asia/Shanghai",
    enable_utc=True,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _utcnow().isoformat(timespec="seconds")


def _persist(settings_obj: Any, operation) -> Any:
    """Celery 任务中的数据库状态回写；失败只告警，不影响主任务。"""
    if not getattr(settings_obj, "database_url", ""):
        return None
    try:
        return task_store.run_async(settings_obj, operation)
    except Exception as exc:  # noqa: BLE001 - 状态回写失败不覆盖业务结果
        print(f"[task-db] 状态持久化失败：{exc}", flush=True)
        return None


@celery_app.task(bind=True, name="zhibiao.parse_pdf")
def parse_pdf_task(
    self,
    job_id: str,
    pdf_path: str,
    original_name: str,
    parser: str = "auto",
    extract: bool = False,
    ingest: bool = False,
) -> dict:
    settings_obj = get_settings()
    started_at = _now_iso()
    retries = int(getattr(self.request, "retries", 0) or 0)
    max_retries = int(getattr(self, "max_retries", 3) or 3)

    _persist(
        settings_obj,
        lambda session: task_store.start_task(
            session,
            job_id,
            stage="parsing",
            retry_count=retries,
            max_retries=max_retries,
        ),
    )

    def set_stage(stage: str) -> None:
        _persist(
            settings_obj,
            lambda session: task_store.update_task(
                session, job_id, status="running", stage=stage
            ),
        )

    @traceable(name="celery.parse_pdf", run_type="chain")
    def run_parse() -> dict:
        parsed = parse_pdf_to_chunks(
            Path(pdf_path), parser=parser, filename=original_name
        )

        if extract:
            set_stage("extracting")
            from .extractor import extract_document

            json_path, _, extraction = extract_document(
                Path(pdf_path), get_settings()
            )
            fields = (extraction.get("project_overview") or {}).get("fields") or []
            parsed["extraction_path"] = str(json_path)
            parsed["extraction_summary"] = {
                "project_name": next(
                    (
                        field.get("value")
                        for field in fields
                        if field.get("name") == "项目名称"
                    ),
                    None,
                ),
                "toc_count": len(extraction.get("toc") or []),
                "scoring_factor_count": len(
                    (extraction.get("evaluation") or {}).get("scoring_factors") or []
                ),
            }

        if ingest:
            set_stage("embedding")
            from .pipeline import ingest_pdf

            ingest_pdf(Path(pdf_path), get_settings(), parser=parser)
            parsed["ingested"] = True
        return parsed

    try:
        result = run_parse()
    except Exception as exc:  # noqa: BLE001 - 记录失败后继续抛出
        _persist(
            settings_obj,
            lambda session: task_store.finish_task(
                session, job_id, "failed", error=str(exc)
            ),
        )
        raise

    result.update(
        {
            "job_id": job_id,
            "started_at": started_at,
            "finished_at": _now_iso(),
        }
    )
    document = _persist(
        settings_obj,
        lambda session: document_store.upsert_document_from_parsed(
            session, settings_obj, result
        ),
    )
    resolved_doc_id = result.get("doc_id") if document is not None else None
    _persist(
        settings_obj,
        lambda session: task_store.finish_task(
            session,
            job_id,
            "succeeded",
            result=result,
            doc_id=resolved_doc_id,
        ),
    )
    return result


@celery_app.task(bind=True, name="bidding.write_bid")
def write_bid_task(
    self,
    job_id: str,
    doc_id: str,
    profile: dict | None = None,
    export_docx: bool = True,
) -> dict:
    settings_obj = get_settings()
    started_at = _now_iso()
    retries = int(getattr(self.request, "retries", 0) or 0)
    max_retries = int(getattr(self, "max_retries", 3) or 3)

    _persist(
        settings_obj,
        lambda session: task_store.start_task(
            session,
            job_id,
            stage="writing_bid",
            retry_count=retries,
            max_retries=max_retries,
        ),
    )

    def progress(stage: str) -> None:
        _persist(
            settings_obj,
            lambda session: task_store.update_task(
                session, job_id, status="running", stage=stage
            ),
        )

    @traceable(name="celery.write_bid", run_type="chain")
    def run_write() -> dict:
        return write_bid(
            doc_id,
            settings=get_settings(),
            profile=profile,
            export_docx=export_docx,
            progress=progress,
        )

    try:
        result = run_write()
    except Exception as exc:  # noqa: BLE001 - 记录失败后继续抛出
        _persist(
            settings_obj,
            lambda session: task_store.finish_task(
                session, job_id, "failed", error=str(exc)
            ),
        )
        raise

    payload = {
        "job_id": job_id,
        "doc_id": doc_id,
        "output_dir": str(result["output_dir"]),
        "markdown_path": str(result["markdown_path"]),
        "docx_path": str(result["docx_path"]) if result.get("docx_path") else None,
        "agent_dir": str(result["agent_dir"]),
        "placeholder_count": int(result.get("placeholder_count") or 0),
        "review": result.get("review") or {},
        "scoring_report": result.get("scoring_report") or {},
        "started_at": started_at,
        "finished_at": _now_iso(),
    }
    _persist(
        settings_obj,
        lambda session: task_store.finish_task(
            session,
            job_id,
            "succeeded",
            result=payload,
            doc_id=doc_id,
        ),
    )
    return payload
