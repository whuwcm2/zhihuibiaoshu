from pathlib import Path

import pytest

from zhibiao import cli


def test_argparse_exit_codes():
    with pytest.raises(SystemExit) as help_exc:
        cli.main(["--help"])
    assert help_exc.value.code == 0

    with pytest.raises(SystemExit) as missing_exc:
        cli.main([])
    assert missing_exc.value.code == 2


def test_ingest_success_returns_zero(monkeypatch):
    captured = {}

    def fake_ingest(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(cli, "ingest_pdf", fake_ingest)

    assert cli.main(["ingest", "x.pdf", "--dry-run"]) == 0
    assert captured["pdf_path"] == Path("x.pdf")
    assert captured["dry_run"] is True


def test_command_error_returns_one(monkeypatch, capsys):
    def fake_ingest(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(cli, "ingest_pdf", fake_ingest)

    assert cli.main(["ingest", "x.pdf"]) == 1
    assert "boom" in capsys.readouterr().err


def test_search_and_extract_dispatch_with_collection_override(monkeypatch):
    captured = {}

    def fake_search(query, settings, n_results):
        captured.update(
            query=query,
            collection=settings.chroma_collection,
            n_results=n_results,
        )

    def fake_extract(pdf_path, settings, output_dir=None, refresh=False):
        captured.update(extract=str(pdf_path), refresh=refresh)

    monkeypatch.setattr(cli, "search", fake_search)
    monkeypatch.setattr(cli, "extract_document", fake_extract)

    assert cli.main(["search", "投标保证金", "-n", "3", "--collection", "foo"]) == 0
    assert captured == {"query": "投标保证金", "collection": "foo", "n_results": 3}

    assert cli.main(["extract", "x.pdf", "--refresh"]) == 0
    assert captured["extract"] == "x.pdf"
    assert captured["refresh"] is True
