from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


def _postgres_dsn(raw: str) -> str:
    parts = urlsplit(raw)
    if parts.scheme not in {"postgresql", "postgresql+asyncpg"}:
        raise SystemExit(f"不支持的 DATABASE_URL scheme: {parts.scheme}")
    return urlunsplit(
        ("postgresql", parts.netloc, parts.path, parts.query, parts.fragment)
    )


def main() -> int:
    raw = os.getenv("DATABASE_URL", "").strip()
    if not raw:
        raise SystemExit("DATABASE_URL 未配置")
    uvx = shutil.which("uvx")
    if not uvx:
        raise SystemExit("未找到 uvx，请先安装 uv")
    env = os.environ.copy()
    # 用环境变量传递，避免连接串出现在进程命令行里
    env["DATABASE_URI"] = _postgres_dsn(raw)
    return subprocess.call(
        [uvx, "postgres-mcp2==0.4.0", "--access-mode=restricted"], env=env
    )


if __name__ == "__main__":
    sys.exit(main())
