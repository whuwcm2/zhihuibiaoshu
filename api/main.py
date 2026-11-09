from __future__ import annotations

import os
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from zhibiao.config import get_settings
from zhibiao.db import create_engine, create_session_factory

from .routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    engine = None
    app.state.engine = None
    app.state.session_factory = None

    if settings.database_url:
        try:
            engine = create_engine(settings)
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            app.state.engine = engine
            app.state.session_factory = create_session_factory(engine)
            print("[db] PostgreSQL 已连接", flush=True)
        except Exception as exc:  # noqa: BLE001 - 数据库不可用不影响解析/投标接口
            print(f"[db] 数据库连接失败，持久化接口不可用：{exc}", flush=True)
            if engine is not None:
                await engine.dispose()

    if os.getenv("SEARCH_WARMUP", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        def _warm_search() -> None:
            try:
                from zhibiao.retrieval import warm_up_embedder

                warm_up_embedder(settings)
            except Exception as exc:  # noqa: BLE001 - 预热失败不影响服务
                print(f"[search] embedding 预热失败：{exc}", flush=True)

        threading.Thread(target=_warm_search, daemon=True).start()

    try:
        yield
    finally:
        engine = getattr(app.state, "engine", None)
        if engine is not None:
            await engine.dispose()
        app.state.engine = None
        app.state.session_factory = None


app = FastAPI(
    title="zhibiao API",
    version="0.1.0",
    description="招标文件上传与解析 API（MinerU 优先，PyMuPDF 兜底）",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/")
def root() -> dict:
    return {
        "name": "zhibiao API",
        "docs": "/docs",
        "health": "/api/health",
        "parse": "POST /api/parse",
        "search": "GET /api/search",
        "documents": "GET /api/documents",
        "tasks": "GET /api/tasks",
        "companies": "GET/POST /api/companies",
    }
