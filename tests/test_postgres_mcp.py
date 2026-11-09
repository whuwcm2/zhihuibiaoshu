from __future__ import annotations

import pytest

from tools.postgres_mcp import _postgres_dsn


def test_postgres_dsn_conversion():
    assert (
        _postgres_dsn("postgresql+asyncpg://user:pass@localhost:5432/bidding")
        == "postgresql://user:pass@localhost:5432/bidding"
    )


def test_postgres_dsn_rejects_other_schemes():
    with pytest.raises(SystemExit):
        _postgres_dsn("mysql://localhost/db")
