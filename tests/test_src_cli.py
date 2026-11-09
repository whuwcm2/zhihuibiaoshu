from __future__ import annotations

import pytest

from src import cli


def test_help_exits_zero():
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--help"])
    assert exc_info.value.code == 0


def test_write_dispatch(monkeypatch):
    captured = {}

    def fake_write(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(cli, "write_bid", fake_write)

    assert cli.main(["write", "doc-1", "--no-docx"]) == 0
    assert captured["doc_id"] == "doc-1"
    assert captured["export_docx"] is False
    assert captured["profile_path"].name == "bidder_profile.json"


def test_write_error_returns_one(monkeypatch, capsys):
    def fake_write(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(cli, "write_bid", fake_write)

    assert cli.main(["write", "doc-1"]) == 1
    assert "boom" in capsys.readouterr().err
