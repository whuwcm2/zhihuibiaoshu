from __future__ import annotations

import json
import re
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import FileResponse
from redis import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from zhibiao import company as company_store
from zhibiao import document_store, task_store
from zhibiao.company import Company
from zhibiao.config import PROJECT_ROOT, get_settings
from zhibiao.db_models import Document, Task
from zhibiao.pipeline import sha1_file
from zhibiao.retrieval import HybridRetriever
from zhibiao.tasks import parse_pdf_task, write_bid_task

from .schemas import (
    BidHistoryItem,
    BidJobCreated,
    BidJobStatus,
    BidRequest,
    BidResult,
    CompanyCreate,
    CompanyDetail,
    CompanySummary,
    DocumentItem,
    ParseJobCreated,
    ParseJobStatus,
    ParseResult,
    SearchIntent,
    SearchResponse,
    TaskHistoryItem,
)

router = APIRouter(prefix="/api")

UPLOAD_DIR = PROJECT_ROOT / "upload" / "files"
MAX_UPLOAD_BYTES = 200 * 1024 * 1024  # MinerU 单文件上限 200MB
MAX_PROFILE_BYTES = 1024 * 1024


def _redis_ok() -> bool:
    client = None
    try:
        client = Redis.from_url(get_settings().redis_url, socket_connect_timeout=1)
        return bool(client.ping())
    except Exception:  # noqa: BLE001 - 健康检查不抛异常
        return False
    finally:
        if client is not None:
            client.close()


@router.get("/health")
def health() -> dict:
    redis_ok = _redis_ok()
    return {
        "status": "ok" if redis_ok else "degraded",
        "service": "zhibiao-api",
        "redis": redis_ok,
    }


@router.get("/search", response_model=SearchResponse)
def search_chunks(
    q: str = Query(..., min_length=1, max_length=500),
    n_results: int = Query(default=5, ge=1, le=20),
    intent: SearchIntent | None = Query(default=None),
) -> dict:
    query = q.strip()
    if not query:
        raise HTTPException(status_code=400, detail="查询不能为空")
    try:
        return HybridRetriever(get_settings()).search(
            query, n_results=n_results, intent=intent
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - 外部检索依赖失败
        raise HTTPException(status_code=502, detail=f"检索失败: {exc}") from exc


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    factory = getattr(request.app.state, "session_factory", None)
    if factory is None:
        raise HTTPException(status_code=503, detail="数据库未配置或不可用")
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


def _company_profile(name: str, profile: dict[str, Any]) -> dict[str, Any]:
    data = dict(profile)
    data["company_name"] = name
    size = len(json.dumps(data, ensure_ascii=False).encode("utf-8"))
    if size > MAX_PROFILE_BYTES:
        raise HTTPException(status_code=413, detail="公司资料超过 1MB 限制")
    return data


@router.post("/companies", response_model=CompanyDetail, status_code=201)
async def create_company(
    payload: CompanyCreate,
    session: AsyncSession = Depends(get_db_session),
) -> Company:
    try:
        return await company_store.create_company(
            session,
            payload.company_name,
            _company_profile(payload.company_name, payload.profile),
        )
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="公司名称已存在") from exc


@router.get("/companies", response_model=list[CompanySummary])
async def list_companies(
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_session),
) -> list[Company]:
    return await company_store.list_companies(
        session, query=q, limit=limit, offset=offset
    )


@router.get("/companies/{company_id}", response_model=CompanyDetail)
async def get_company(
    company_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> Company:
    company = await company_store.get_company(session, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="公司信息不存在")
    return company


@router.put("/companies/{company_id}", response_model=CompanyDetail)
async def update_company(
    company_id: uuid.UUID,
    payload: CompanyCreate,
    session: AsyncSession = Depends(get_db_session),
) -> Company:
    company = await company_store.get_company(session, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="公司信息不存在")
    try:
        return await company_store.update_company(
            session,
            company,
            payload.company_name,
            _company_profile(payload.company_name, payload.profile),
        )
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="公司名称已存在") from exc


@router.delete("/companies/{company_id}", status_code=204)
async def delete_company(
    company_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    company = await company_store.get_company(session, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="公司信息不存在")
    await company_store.delete_company(session, company)
    return Response(status_code=204)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _task_result(task: Task, fields: dict) -> dict[str, Any] | None:
    if task.status != "succeeded" or not isinstance(task.result, dict):
        return None
    return {
        key: task.result.get(key)
        for key in fields
        if task.result.get(key) is not None
    }


@router.post("/parse", response_model=ParseJobCreated, status_code=202)
async def create_parse_job(
    file: UploadFile = File(..., description="PDF 招标文件"),
    parser: Literal["auto", "mineru", "pymupdf"] = Form("auto"),
    extract: bool = Form(False),
    ingest: bool = Form(False),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    original_name = Path(file.filename or "").name.lstrip(".")
    original_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", original_name)
    if not original_name or not original_name.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="只接受 .pdf 文件")

    job_id = uuid.uuid4().hex
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    temp_path = UPLOAD_DIR / f".{job_id}.upload"

    size = 0
    try:
        with temp_path.open("wb") as handle:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="文件超过 200MB 限制")
                handle.write(chunk)

        with temp_path.open("rb") as handle:
            if handle.read(4) != b"%PDF":
                raise HTTPException(status_code=400, detail="文件不是有效的 PDF")

        # 用内容 SHA1 命名，保证同一份 PDF 重复上传得到稳定的 doc_id
        digest = sha1_file(temp_path)
        target = UPLOAD_DIR / f"{digest[:12]}_{original_name}"
        temp_path.replace(target)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    finally:
        await file.close()

    try:
        await task_store.create_task(
            session,
            job_id,
            "parse_pdf",
            payload={
                "filename": original_name,
                "parser": parser,
                "extract": extract,
                "ingest": ingest,
            },
        )
    except Exception as exc:  # noqa: BLE001 - 数据库不可用
        raise HTTPException(
            status_code=503, detail=f"任务状态存储不可用: {exc}"
        ) from exc

    try:
        parse_pdf_task.apply_async(
            args=[job_id, str(target), original_name, parser, extract, ingest],
            task_id=job_id,
        )
    except Exception as exc:  # noqa: BLE001 - Redis/Celery 不可用
        try:
            await task_store.finish_task(
                session, job_id, "failed", error=f"任务队列不可用: {exc}"
            )
        except Exception:  # noqa: BLE001 - 状态回写失败不应覆盖原始异常
            pass
        raise HTTPException(
            status_code=503, detail=f"任务队列不可用: {exc}"
        ) from exc

    return {
        "job_id": job_id,
        "status": "pending",
        "filename": original_name,
        "status_url": f"/api/parse/{job_id}",
    }


@router.get("/parse/{job_id}", response_model=ParseJobStatus)
async def get_parse_job(
    job_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    task = await task_store.get_task(session, job_id)
    if task is None or task.task_type != "parse_pdf":
        raise HTTPException(status_code=404, detail="任务不存在")

    result = _task_result(task, ParseResult.model_fields)
    payload = task.payload or {}
    return {
        "job_id": task.id,
        "filename": payload.get("filename") or (result or {}).get("filename") or "",
        "status": task.status,
        "stage": task.stage if task.status == "running" else None,
        "created_at": _iso(task.created_at) or "",
        "started_at": _iso(task.started_at),
        "finished_at": _iso(task.finished_at),
        "result": result,
        "error": task.error if task.status == "failed" else None,
    }


async def _resolve_bid_profile(
    payload: BidRequest, session: AsyncSession
) -> dict[str, Any]:
    if payload.profile is not None:
        return payload.profile
    if payload.company_id is not None:
        company = await company_store.get_company(session, payload.company_id)
        if company is None:
            raise HTTPException(status_code=404, detail="公司信息不存在")
        return dict(company.profile)
    profile_file = PROJECT_ROOT / "bidder_profile.json"
    if not profile_file.exists():
        return {}
    try:
        data = json.loads(profile_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=500, detail=f"bidder_profile.json 无效: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=500, detail="bidder_profile.json 顶层必须是对象")
    return data


@router.post("/bids", response_model=BidJobCreated, status_code=202)
async def create_bid_job(
    payload: BidRequest,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    doc_id = payload.doc_id.strip()
    if not doc_id or "/" in doc_id or "\\" in doc_id or ".." in doc_id:
        raise HTTPException(status_code=400, detail="无效的 doc_id")

    settings = get_settings()
    extraction = settings.data_dir / "parsed" / doc_id / "extraction.json"
    if not extraction.exists():
        raise HTTPException(
            status_code=404,
            detail=f"未找到 doc_id={doc_id} 的抽取结果，请先执行 ingest 和 extract",
        )

    profile = await _resolve_bid_profile(payload, session)
    profile_size = len(json.dumps(profile, ensure_ascii=False).encode("utf-8"))
    if profile_size > MAX_PROFILE_BYTES:
        raise HTTPException(status_code=413, detail="profile 超过 1MB 限制")

    document = await session.get(Document, doc_id)
    job_id = uuid.uuid4().hex
    task_payload: dict[str, Any] = {
        "doc_id": doc_id,
        "export_docx": payload.export_docx,
    }
    if payload.company_id is not None:
        task_payload["company_id"] = str(payload.company_id)
    try:
        await task_store.create_task(
            session,
            job_id,
            "write_bid",
            payload=task_payload,
            doc_id=doc_id if document is not None else None,
            project_id=document.project_id if document is not None else None,
        )
    except Exception as exc:  # noqa: BLE001 - 数据库不可用
        raise HTTPException(
            status_code=503, detail=f"任务状态存储不可用: {exc}"
        ) from exc

    try:
        write_bid_task.apply_async(
            args=[job_id, doc_id, profile, payload.export_docx],
            task_id=job_id,
        )
    except Exception as exc:  # noqa: BLE001 - Redis/Celery 不可用
        try:
            await task_store.finish_task(
                session, job_id, "failed", error=f"任务队列不可用: {exc}"
            )
        except Exception:  # noqa: BLE001 - 状态回写失败不应覆盖原始异常
            pass
        raise HTTPException(
            status_code=503, detail=f"任务队列不可用: {exc}"
        ) from exc

    return {
        "job_id": job_id,
        "status": "pending",
        "doc_id": doc_id,
        "status_url": f"/api/bids/{job_id}",
    }


@router.get("/bids/{job_id}", response_model=BidJobStatus)
async def get_bid_job(
    job_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    task = await task_store.get_task(session, job_id)
    if task is None or task.task_type != "write_bid":
        raise HTTPException(status_code=404, detail="任务不存在")

    result = _task_result(task, BidResult.model_fields)
    payload = task.payload or {}
    return {
        "job_id": task.id,
        "doc_id": task.doc_id or payload.get("doc_id"),
        "status": task.status,
        "stage": task.stage if task.status == "running" else None,
        "created_at": _iso(task.created_at) or "",
        "started_at": _iso(task.started_at),
        "finished_at": _iso(task.finished_at),
        "result": result,
        "error": task.error if task.status == "failed" else None,
    }


@router.get("/tasks", response_model=list[TaskHistoryItem])
async def list_task_history(
    task_type: Literal["parse_pdf", "write_bid"] | None = Query(default=None),
    status: Literal["pending", "running", "succeeded", "failed"] | None = Query(
        default=None
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_session),
) -> list[Task]:
    return await task_store.list_tasks(
        session,
        task_type=task_type,
        status=status,
        limit=limit,
        offset=offset,
    )


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def _bid_roots(settings) -> list[Path]:
    roots = [settings.data_dir / "bids"]
    upload_root = PROJECT_ROOT / "upload" / "bids"
    if upload_root.exists():
        roots.append(upload_root)
    return roots


@router.get("/documents", response_model=list[DocumentItem])
async def list_documents(
    session: AsyncSession = Depends(get_db_session),
) -> list[DocumentItem]:
    statement = (
        select(Document)
        .options(selectinload(Document.project))
        .order_by(Document.created_at.desc())
    )
    documents = (await session.scalars(statement)).all()
    return [
        DocumentItem(
            doc_id=document.doc_id,
            project_id=document.project_id,
            project_name=document.project.name if document.project else None,
            source=document.source,
            page_count=document.page_count,
            parser=document.parser,
            created_at=document.created_at,
            chunk_count=document.chunk_count,
            has_extraction=document.has_extraction,
            root=document.root,
        )
        for document in documents
    ]


@router.get("/bids", response_model=list[BidHistoryItem])
def list_bid_history() -> list[BidHistoryItem]:
    settings = get_settings()
    items: dict[str, BidHistoryItem] = {}
    for root in _bid_roots(settings):
        if not root.exists():
            continue
        for doc_dir in root.iterdir():
            if not doc_dir.is_dir() or doc_dir.name in items:
                continue
            meta = _load_json(doc_dir / "bid_meta.json") or {}
            markdown = doc_dir / "bid.md"
            docx = doc_dir / "bid.docx"
            if not meta and not markdown.exists():
                continue
            review = meta.get("review") or {}
            items[doc_dir.name] = BidHistoryItem(
                doc_id=doc_dir.name,
                project_name=meta.get("project_name"),
                company_name=meta.get("company_name"),
                generated_at=meta.get("generated_at"),
                placeholder_count=int(meta.get("placeholder_count") or 0),
                review_summary=str(review.get("summary") or ""),
                has_docx=docx.exists(),
                output_dir=str(doc_dir),
                markdown_path=str(markdown) if markdown.exists() else "",
                docx_path=str(docx) if docx.exists() else None,
            )
    return sorted(items.values(), key=lambda item: item.generated_at or "", reverse=True)


@router.get("/bids/{doc_id}/files/{filename}")
def get_bid_file(doc_id: str, filename: str, download: bool = True):
    if not doc_id or "/" in doc_id or "\\" in doc_id or ".." in doc_id:
        raise HTTPException(status_code=400, detail="无效的 doc_id")
    allowed = {
        "bid.md": "text/markdown; charset=utf-8",
        "bid.docx": (
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
        "bid_meta.json": "application/json",
    }
    if filename not in allowed:
        raise HTTPException(status_code=404, detail="文件不存在")

    settings = get_settings()
    for root in _bid_roots(settings):
        path = root / doc_id / filename
        if path.exists():
            if download:
                return FileResponse(
                    path, media_type=allowed[filename], filename=filename
                )
            return FileResponse(path, media_type=allowed[filename])
    raise HTTPException(status_code=404, detail="文件不存在")
