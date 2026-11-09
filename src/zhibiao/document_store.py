from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import PROJECT_ROOT, Settings
from .db_models import Document, Project

PLACEHOLDER = "【待填写】"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def _count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for _ in handle)


def _project_name(extraction: dict[str, Any] | None) -> str | None:
    if not extraction:
        return None
    fields = (extraction.get("project_overview") or {}).get("fields") or []
    value = next(
        (
            field.get("value")
            for field in fields
            if field.get("name") == "项目名称" and field.get("value")
        ),
        None,
    )
    if not value or value == PLACEHOLDER:
        return None
    return str(value).strip() or None


async def get_or_create_project(
    session: AsyncSession, name: str
) -> Project:
    project = await session.scalar(select(Project).where(Project.name == name))
    if project is not None:
        return project
    project = Project(name=name)
    session.add(project)
    await session.flush()
    return project


async def upsert_document(
    session: AsyncSession,
    *,
    doc_id: str,
    filename: str,
    source: str | None = None,
    root: str = "",
    page_count: int = 0,
    parser: str | None = None,
    chunk_count: int = 0,
    has_extraction: bool = False,
    created_at: datetime | None = None,
    project_id: Any | None = None,
) -> Document:
    document = await session.get(Document, doc_id)
    if document is None:
        document = Document(
            doc_id=doc_id,
            filename=filename or doc_id,
            created_at=created_at or _utcnow(),
        )
        session.add(document)
    document.filename = filename or document.filename
    document.source = source
    document.root = root
    document.page_count = page_count
    document.parser = parser
    document.chunk_count = chunk_count
    document.has_extraction = has_extraction
    if project_id is not None:
        document.project_id = project_id
    await session.commit()
    await session.refresh(document)
    return document


async def upsert_document_from_dir(
    session: AsyncSession, doc_dir: Path, root: Path
) -> Document:
    manifest = _load_json(doc_dir / "manifest.json") or {}
    extraction = _load_json(doc_dir / "extraction.json")
    project = None
    project_name = _project_name(extraction)
    if project_name:
        project = await get_or_create_project(session, project_name)

    source = manifest.get("source") or (extraction or {}).get("source")
    filename = Path(source).name if source else doc_dir.name
    created_at = _parse_datetime(
        manifest.get("created_at") or (extraction or {}).get("generated_at")
    )
    return await upsert_document(
        session,
        doc_id=doc_dir.name,
        filename=filename,
        source=source,
        root=str(root),
        page_count=int(manifest.get("page_count") or 0),
        parser=manifest.get("parser"),
        chunk_count=_count_lines(doc_dir / "chunks.jsonl"),
        has_extraction=extraction is not None,
        created_at=created_at,
        project_id=project.id if project is not None else None,
    )


async def upsert_document_from_parsed(
    session: AsyncSession,
    settings: Settings,
    parsed: dict[str, Any],
) -> Document | None:
    doc_id = parsed.get("doc_id")
    if not doc_id:
        return None
    for root in (settings.data_dir / "parsed", PROJECT_ROOT / "upload" / "parsed"):
        doc_dir = root / doc_id
        if doc_dir.is_dir():
            return await upsert_document_from_dir(session, doc_dir, root)
    return await upsert_document(
        session,
        doc_id=str(doc_id),
        filename=str(parsed.get("filename") or doc_id),
        root=str(settings.data_dir / "parsed"),
        page_count=int(parsed.get("page_count") or 0),
        parser=parsed.get("parser"),
        chunk_count=int(parsed.get("chunk_count") or 0),
        has_extraction=bool(parsed.get("extraction_path")),
    )


async def backfill_documents(
    session: AsyncSession, settings: Settings
) -> int:
    count = 0
    roots = [settings.data_dir / "parsed", PROJECT_ROOT / "upload" / "parsed"]
    for root in roots:
        if not root.exists():
            continue
        for doc_dir in sorted(root.iterdir()):
            if not doc_dir.is_dir():
                continue
            if not (
                (doc_dir / "manifest.json").exists()
                or (doc_dir / "chunks.jsonl").exists()
                or (doc_dir / "extraction.json").exists()
            ):
                continue
            await upsert_document_from_dir(session, doc_dir, root)
            count += 1
    return count
