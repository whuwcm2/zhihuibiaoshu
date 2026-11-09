from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from .config import Settings
from .db_models import Document, Task

T = TypeVar("T")
TaskOperation = Callable[[AsyncSession], Awaitable[T]]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def create_task(
    session: AsyncSession,
    job_id: str,
    task_type: str,
    payload: dict[str, Any] | None = None,
    doc_id: str | None = None,
    project_id: Any | None = None,
    user_id: Any | None = None,
) -> Task:
    task = Task(
        id=job_id,
        task_type=task_type,
        status="pending",
        payload=payload or {},
        doc_id=doc_id,
        project_id=project_id,
        user_id=user_id,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


async def get_task(session: AsyncSession, job_id: str) -> Task | None:
    return await session.get(Task, job_id)


async def list_tasks(
    session: AsyncSession,
    task_type: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Task]:
    statement = select(Task).order_by(Task.created_at.desc())
    if task_type:
        statement = statement.where(Task.task_type == task_type)
    if status:
        statement = statement.where(Task.status == status)
    statement = statement.limit(limit).offset(offset)
    result = await session.scalars(statement)
    return list(result)


async def update_task(
    session: AsyncSession, job_id: str, **fields: Any
) -> Task | None:
    task = await session.get(Task, job_id)
    if task is None:
        return None
    for key, value in fields.items():
        setattr(task, key, value)
    await session.commit()
    await session.refresh(task)
    return task


async def start_task(
    session: AsyncSession,
    job_id: str,
    stage: str | None = None,
    retry_count: int = 0,
    max_retries: int = 3,
) -> Task | None:
    task = await session.get(Task, job_id)
    if task is None:
        return None
    task.status = "running"
    task.stage = stage
    task.retry_count = retry_count
    task.max_retries = max_retries
    task.error = None
    if task.started_at is None:
        task.started_at = _utcnow()
    await session.commit()
    await session.refresh(task)
    return task


async def finish_task(
    session: AsyncSession,
    job_id: str,
    status: str,
    result: dict[str, Any] | None = None,
    error: str | None = None,
    doc_id: str | None = None,
) -> Task | None:
    task = await session.get(Task, job_id)
    if task is None:
        return None
    finished = _utcnow()
    task.status = status
    task.stage = None
    task.result = result
    task.error = error
    task.finished_at = finished
    if doc_id and await session.get(Document, doc_id) is not None:
        task.doc_id = doc_id
    if task.started_at is not None:
        started = task.started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        task.duration_ms = max(0, int((finished - started).total_seconds() * 1000))
    await session.commit()
    await session.refresh(task)
    return task


async def _run(settings: Settings, operation: TaskOperation[T]) -> T:
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            return await operation(session)
    finally:
        await engine.dispose()


def run_async(settings: Settings, operation: TaskOperation[T]) -> T:
    """在 Celery 同步任务中执行一次数据库操作。

    每次创建一个独立的 NullPool engine，避免 asyncpg 连接跨事件循环复用。
    """
    if not getattr(settings, "database_url", ""):
        raise RuntimeError("DATABASE_URL 未配置")
    return asyncio.run(_run(settings, operation))
