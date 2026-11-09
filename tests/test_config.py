from pathlib import Path

from zhibiao.config import (
    PROJECT_ROOT,
    _as_bool,
    _mineru_base_url,
    _resolve_path,
    get_settings,
)


def test_path_url_and_bool_helpers(tmp_path: Path):
    assert _resolve_path(str(tmp_path / "x"), "./y") == tmp_path / "x"
    assert _resolve_path("relative", "./fallback") == (PROJECT_ROOT / "relative").resolve()
    assert _mineru_base_url("https://mineru.net/api/v4/extract/task") == "https://mineru.net/api/v4"
    assert _mineru_base_url("not-a-url") == "https://mineru.net/api/v4"
    assert [_as_bool(value) for value in [None, "true", "1", "yes", "on", "0", "false"]] == [
        False,
        True,
        True,
        True,
        True,
        False,
        False,
    ]


def test_get_settings_env_override(monkeypatch):
    monkeypatch.setenv("ZHIPU_API_KEY", "zk-test")
    monkeypatch.setenv("EMBEDDING_MODEL", "embedding-3")
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "512")
    monkeypatch.setenv("CHROMA_DIR", "./chroma_x")
    monkeypatch.setenv("MINERU_ENDPOINT", "https://example.com/api/v4/extract/task")
    monkeypatch.setenv("MINERU_MODE", "off")
    monkeypatch.setenv("MINERU_MAX_POLLS", "7")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6390/1")
    monkeypatch.setenv("CELERY_BROKER_URL", "redis://127.0.0.1:6390/2")
    monkeypatch.setenv("CELERY_RESULT_BACKEND", "redis://127.0.0.1:6390/3")
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/test_db"
    )

    settings = get_settings()

    assert settings.zhipu_api_key == "zk-test"
    assert settings.embedding_dimensions == 512
    assert settings.chroma_dir == (PROJECT_ROOT / "chroma_x").resolve()
    assert settings.mineru_base_url == "https://example.com/api/v4"
    assert settings.mineru_enabled is False
    assert settings.mineru_max_polls == 7
    assert settings.redis_url == "redis://127.0.0.1:6390/1"
    assert settings.celery_broker_url == "redis://127.0.0.1:6390/2"
    assert settings.celery_result_backend == "redis://127.0.0.1:6390/3"
    assert settings.database_url == "postgresql+asyncpg://user:pass@localhost:5432/test_db"
