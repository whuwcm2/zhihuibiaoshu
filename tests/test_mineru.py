from __future__ import annotations

import io
import zipfile
from dataclasses import replace
from pathlib import Path

import httpx
import pymupdf
import pytest

from zhibiao import mineru
from zhibiao.mineru import (
    MinerUCloudParser,
    MinerUError,
    PdfPart,
    split_pdf,
)


class FakeResponse:
    def __init__(self, status_code=200, payload=None, content: bytes = b"", text: str = ""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.content = content
        self.text = text
        self.request = httpx.Request("GET", "https://test.local")

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}", request=self.request, response=self
            )

    def iter_bytes(self):
        yield self.content


def test_init_requires_api_key(settings):
    with pytest.raises(MinerUError):
        MinerUCloudParser(replace(settings, mineru_api_key=""))


def test_split_pdf_returns_original_when_small(settings, make_pdf):
    pdf_path = make_pdf(pages=3)
    parts = split_pdf(pdf_path, settings.data_dir / "parts")

    assert len(parts) == 1
    assert parts[0].path == pdf_path
    assert parts[0].page_start == 1
    assert parts[0].page_count == 3
    assert parts[0].page_offset == 0


def test_split_pdf_creates_parts_with_offsets(settings, make_pdf, monkeypatch):
    monkeypatch.setattr(mineru, "MAX_PAGES_PER_PART", 2)
    pdf_path = make_pdf(pages=5)

    parts = split_pdf(pdf_path, settings.data_dir / "parts")

    assert [(part.page_start, part.page_count, part.page_offset) for part in parts] == [
        (1, 2, 0),
        (3, 2, 2),
        (5, 1, 4),
    ]
    assert [pymupdf.open(part.path).page_count for part in parts] == [2, 2, 1]


def test_request_upload_urls_payload_and_success(settings, tmp_path, monkeypatch):
    parser = MinerUCloudParser(settings)
    parts = [
        PdfPart(tmp_path / "a.pdf", "a.pdf", 1, 10, 0),
        PdfPart(tmp_path / "b.pdf", "b.pdf", 11, 10, 10),
    ]
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return FakeResponse(
            payload={"code": 0, "data": {"batch_id": "b1", "file_urls": ["u1", "u2"]}}
        )

    monkeypatch.setattr(mineru.httpx, "request", fake_request)

    batch_id, urls = parser._request_upload_urls(parts, "doc123")

    assert batch_id == "b1"
    assert urls == ["u1", "u2"]
    payload = calls[0][2]["json"]
    assert payload["model_version"] == "vlm"
    assert payload["files"][0] == {"name": "a.pdf", "data_id": "doc123-p1", "is_ocr": True}
    assert calls[0][2]["headers"]["Authorization"] == "Bearer test-mineru"

    monkeypatch.setattr(
        mineru.httpx,
        "request",
        lambda *args, **kwargs: FakeResponse(
            payload={"code": 0, "data": {"batch_id": "b1", "file_urls": ["only-one"]}}
        ),
    )
    with pytest.raises(MinerUError):
        parser._request_upload_urls(parts, "doc")


def test_request_json_retries_then_raises(settings, monkeypatch):
    parser = MinerUCloudParser(settings)
    calls = []

    def fake_request(*args, **kwargs):
        calls.append(1)
        raise httpx.ConnectError("network down")

    monkeypatch.setattr(mineru.httpx, "request", fake_request)

    with pytest.raises(MinerUError):
        parser._request_json("GET", "https://mineru.test/x")
    assert len(calls) == 3

    monkeypatch.setattr(
        mineru.httpx,
        "request",
        lambda *args, **kwargs: FakeResponse(payload={"code": 100, "msg": "bad token"}),
    )
    with pytest.raises(MinerUError, match="bad token"):
        parser._request_json("GET", "https://mineru.test/x")


def test_upload_parts_failure(settings, tmp_path, monkeypatch):
    parser = MinerUCloudParser(settings)
    part = PdfPart(tmp_path / "a.pdf", "a.pdf", 1, 1, 0)
    part.path.write_bytes(b"%PDF-1.4 fake")

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def put(self, url, content):
            return FakeResponse(status_code=500, text="upload failed")

    monkeypatch.setattr(mineru.httpx, "Client", FakeClient)

    with pytest.raises(MinerUError, match="上传"):
        parser._upload_parts([part], ["https://upload"])


def test_wait_for_results_done(settings, monkeypatch):
    parser = MinerUCloudParser(settings)
    payload = {
        "data": {
            "extract_result": [
                {"file_name": "a.pdf", "state": "done", "full_zip_url": "https://zip"}
            ]
        }
    }
    monkeypatch.setattr(parser, "_request_json", lambda *args, **kwargs: payload)

    results = parser._wait_for_results("batch", expected=1)

    assert results[0]["state"] == "done"


def test_wait_for_results_failed_and_timeout(settings, monkeypatch):
    parser = MinerUCloudParser(settings)
    failed = {
        "data": {
            "extract_result": [
                {"file_name": "a.pdf", "state": "failed", "err_msg": "文件损坏"}
            ]
        }
    }
    monkeypatch.setattr(parser, "_request_json", lambda *args, **kwargs: failed)
    with pytest.raises(MinerUError, match="文件损坏"):
        parser._wait_for_results("batch", expected=1)

    running = {
        "data": {"extract_result": [{"file_name": "a.pdf", "state": "running"}]}
    }
    monkeypatch.setattr(parser, "_request_json", lambda *args, **kwargs: running)
    with pytest.raises(MinerUError, match="超时"):
        parser._wait_for_results("batch", expected=1)


def test_download_results_and_merge_markdown(settings, tmp_path, monkeypatch):
    parser = MinerUCloudParser(settings)
    part = PdfPart(tmp_path / "a.pdf", "a.pdf", 1, 2, 0)
    part.path.write_bytes(b"%PDF-1.4 fake")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("result/full.md", "## 标题\n\n正文")
        archive.writestr("result/x_content_list.json", "[]")
    zip_bytes = buffer.getvalue()

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def stream(self, method, url):
            response = FakeResponse(content=zip_bytes)

            class Ctx:
                def __enter__(self):
                    return response

                def __exit__(self, *args):
                    return False

            return Ctx()

    monkeypatch.setattr(mineru.httpx, "Client", FakeClient)

    parsed = parser._download_results(
        [part],
        [{"file_name": "a.pdf", "state": "done", "full_zip_url": "https://zip"}],
        tmp_path / "doc",
    )

    assert "正文" in parsed[0].markdown_path.read_text(encoding="utf-8")
    assert parsed[0].content_list_path is not None

    merged = parser._merge_markdown(parsed, tmp_path / "doc" / "combined.md")
    assert "<!-- part 1: pages 1-2 -->" in merged.read_text(encoding="utf-8")
