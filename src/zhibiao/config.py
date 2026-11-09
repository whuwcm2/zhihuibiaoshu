from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


def _resolve_path(value: str | None, default: str) -> Path:
    path = Path(value or default)
    return path if path.is_absolute() else (PROJECT_ROOT / path).resolve()


def _mineru_base_url(endpoint: str) -> str:
    parts = urlsplit(endpoint)
    if parts.scheme and parts.netloc:
        return f"{parts.scheme}://{parts.netloc}/api/v4"
    return "https://mineru.net/api/v4"


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    llm_provider: str
    deepseek_api_key: str
    deepseek_model: str
    deepseek_base_url: str

    zhipu_api_key: str
    embedding_model: str
    embedding_dimensions: int | None
    chroma_dir: Path
    chroma_collection: str

    mineru_enabled: bool
    mineru_api_key: str
    mineru_base_url: str
    mineru_model_version: str
    mineru_timeout: int
    mineru_poll_interval: int
    mineru_max_polls: int
    mineru_is_ocr: bool

    data_dir: Path
    chunk_max_chars: int
    chunk_overlap: int

    redis_url: str
    celery_broker_url: str
    celery_result_backend: str
    database_url: str = ""


def get_settings() -> Settings:
    endpoint = os.getenv("MINERU_ENDPOINT", "https://mineru.net/api/v4/extract/task")
    mode = (os.getenv("MINERU_MODE", "cloud") or "cloud").strip().lower()
    dimensions = os.getenv("EMBEDDING_DIMENSIONS")
    redis_url = (os.getenv("REDIS_URL") or "redis://localhost:6379/0").strip()
    return Settings(
        llm_provider=os.getenv("LLM_PROVIDER", "deepseek").strip().lower(),
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", "").strip(),
        deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip(),
        deepseek_base_url=(os.getenv("DEEPSEEK_BASE_URL") or "https://api.deepseek.com").strip(),
        zhipu_api_key=os.getenv("ZHIPU_API_KEY", "").strip(),
        embedding_model=os.getenv("EMBEDDING_MODEL", "embedding-3").strip(),
        embedding_dimensions=int(dimensions) if dimensions else None,
        chroma_dir=_resolve_path(os.getenv("CHROMA_DIR"), "./chroma_db"),
        chroma_collection=os.getenv("CHROMA_COLLECTION", "bid_documents").strip(),
        mineru_enabled=mode not in {"off", "disabled", "false", "0", "none"},
        mineru_api_key=os.getenv("MINERU_API_KEY", "").strip(),
        mineru_base_url=_mineru_base_url(endpoint),
        mineru_model_version=os.getenv("MINERU_MODEL_VERSION", "vlm").strip(),
        mineru_timeout=int(os.getenv("MINERU_TIMEOUT", "180")),
        mineru_poll_interval=int(os.getenv("MINERU_POLL_INTERVAL", "5")),
        mineru_max_polls=int(os.getenv("MINERU_MAX_POLLS", "360")),
        mineru_is_ocr=_as_bool(os.getenv("MINERU_IS_OCR"), True),
        data_dir=_resolve_path(os.getenv("DATA_DIR"), "./data"),
        chunk_max_chars=int(os.getenv("CHUNK_MAX_CHARS", "1000")),
        chunk_overlap=int(os.getenv("CHUNK_OVERLAP", "120")),
        redis_url=redis_url,
        celery_broker_url=(os.getenv("CELERY_BROKER_URL") or redis_url).strip(),
        celery_result_backend=(os.getenv("CELERY_RESULT_BACKEND") or redis_url).strip(),
        database_url=os.getenv("DATABASE_URL", "").strip(),
    )
