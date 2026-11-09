from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pymupdf
import pytest

from zhibiao.config import Settings


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """所有重试/轮询测试不真正等待。"""
    monkeypatch.setattr(time, "sleep", lambda *args, **kwargs: None)


@pytest.fixture(autouse=True)
def _disable_langsmith(monkeypatch):
    """测试不访问 LangSmith：关闭 tracing 与 Prompt Hub 拉取。"""
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGSMITH_PROMPT_HUB", "false")


@pytest.fixture(autouse=True)
def _disable_database(monkeypatch):
    """默认不连接真实 PostgreSQL；需要数据库的测试通过 db_path 覆盖。"""
    monkeypatch.setenv("DATABASE_URL", "")


@pytest.fixture
def db_path(tmp_path: Path, monkeypatch) -> Path:
    path = tmp_path / "zhibiao-test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{path.as_posix()}")
    return path


@pytest.fixture
def db_run(db_path: Path):
    """在测试主线程中用独立 engine 执行一次异步数据库操作。"""
    from zhibiao.config import get_settings
    from zhibiao.db import create_engine, create_session_factory

    def _run(operation):
        async def runner():
            engine = create_engine(get_settings())
            factory = create_session_factory(engine)
            try:
                async with factory() as session:
                    return await operation(session)
            finally:
                await engine.dispose()

        return asyncio.run(runner())

    return _run


@pytest.fixture
def db_client(db_path: Path):
    from fastapi.testclient import TestClient

    from api.main import app
    from zhibiao.config import get_settings
    from zhibiao.db import create_engine, init_db

    async def setup() -> None:
        engine = create_engine(get_settings())
        try:
            await init_db(engine)
        finally:
            await engine.dispose()

    asyncio.run(setup())
    with TestClient(app) as client:
        yield client


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        llm_provider="deepseek",
        deepseek_api_key="test-deepseek",
        deepseek_model="deepseek-flash",
        deepseek_base_url="https://api.deepseek.com",
        zhipu_api_key="test-zhipu",
        embedding_model="embedding-3",
        embedding_dimensions=1024,
        chroma_dir=tmp_path / "chroma",
        chroma_collection="test_collection",
        mineru_enabled=True,
        mineru_api_key="test-mineru",
        mineru_base_url="https://mineru.test/api/v4",
        mineru_model_version="vlm",
        mineru_timeout=5,
        mineru_poll_interval=2,
        mineru_max_polls=60,
        mineru_is_ocr=True,
        data_dir=tmp_path / "data",
        chunk_max_chars=1000,
        chunk_overlap=120,
        redis_url="redis://localhost:6379/0",
        celery_broker_url="redis://localhost:6379/0",
        celery_result_backend="redis://localhost:6379/0",
    )


@pytest.fixture
def make_pdf(tmp_path: Path):
    def _make(name: str = "doc.pdf", pages: int = 3) -> Path:
        path = tmp_path / name
        document = pymupdf.open()
        for index in range(pages):
            page = document.new_page()
            page.insert_text((72, 72), f"Page {index + 1} tender document")
        document.save(str(path))
        document.close()
        return path

    return _make
