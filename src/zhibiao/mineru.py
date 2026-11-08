from __future__ import annotations

import json
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

import httpx
import pymupdf

from .config import Settings

MAX_PAGES_PER_PART = 200


class MinerUError(RuntimeError):
    pass


@dataclass
class PdfPart:
    path: Path
    name: str
    page_start: int  # 1-based，含
    page_count: int
    page_offset: int  # 在本分片之前的总页数（0-based）


@dataclass
class ParsedPart:
    part: PdfPart
    output_dir: Path
    markdown_path: Path
    content_list_path: Path | None


@dataclass
class MinerUResult:
    doc_dir: Path
    parts: list[ParsedPart]
    combined_markdown: Path


def split_pdf(pdf_path: Path, out_dir: Path) -> list[PdfPart]:
    """MinerU 单文件最多 200 页，超出时用 PyMuPDF 本地拆分。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    with pymupdf.open(pdf_path) as doc:
        total = doc.page_count
        if total <= MAX_PAGES_PER_PART:
            return [PdfPart(path=pdf_path, name=pdf_path.name, page_start=1,
                            page_count=total, page_offset=0)]

        parts: list[PdfPart] = []
        for start in range(0, total, MAX_PAGES_PER_PART):
            end = min(start + MAX_PAGES_PER_PART, total) - 1
            name = f"{pdf_path.stem}_p{start + 1:04d}-{end + 1:04d}.pdf"
            part_path = out_dir / name
            with pymupdf.open() as part_doc:
                part_doc.insert_pdf(doc, from_page=start, to_page=end)
                part_doc.save(part_path)
            parts.append(
                PdfPart(
                    path=part_path,
                    name=name,
                    page_start=start + 1,
                    page_count=end - start + 1,
                    page_offset=start,
                )
            )
    return parts


class MinerUCloudParser:
    """MinerU 精准解析云端 API（本地文件上传 → 轮询 → 下载 zip）。"""

    def __init__(self, settings: Settings) -> None:
        if not settings.mineru_api_key:
            raise MinerUError("MINERU_API_KEY 未配置")
        self.settings = settings
        self.base_url = settings.mineru_base_url.rstrip("/")
        self.auth_headers = {
            "Authorization": f"Bearer {settings.mineru_api_key}",
            "Accept": "*/*",
        }

    def parse(self, pdf_path: Path, doc_id: str, doc_dir: Path) -> MinerUResult:
        parts_dir = doc_dir / "parts"
        parts = split_pdf(pdf_path, parts_dir)
        print(f"[mineru] 共 {sum(p.page_count for p in parts)} 页，切分为 {len(parts)} 个上传分片", flush=True)

        batch_id, upload_urls = self._request_upload_urls(parts, doc_id)
        print(f"[mineru] batch_id={batch_id}，开始上传 {len(parts)} 个分片", flush=True)
        self._upload_parts(parts, upload_urls)

        print("[mineru] 上传完成，等待云端解析…", flush=True)
        results = self._wait_for_results(batch_id, len(parts))
        parsed_parts = self._download_results(parts, results, doc_dir)
        combined = self._merge_markdown(parsed_parts, doc_dir / "mineru_full.md")
        return MinerUResult(doc_dir=doc_dir, parts=parsed_parts, combined_markdown=combined)

    # ---------- HTTP helpers ----------

    def _request_json(self, method: str, url: str, **kwargs) -> dict:
        headers = {**self.auth_headers, **kwargs.pop("headers", {})}
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = httpx.request(
                    method, url, headers=headers,
                    timeout=self.settings.mineru_timeout, follow_redirects=True, **kwargs,
                )
                if response.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        f"HTTP {response.status_code}", request=response.request, response=response
                    )
                response.raise_for_status()
                payload = response.json()
                if payload.get("code") != 0:
                    raise MinerUError(
                        f"MinerU API 错误 code={payload.get('code')}: {payload.get('msg')}"
                    )
                return payload
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(2 * (attempt + 1))
        raise MinerUError(f"请求 MinerU 失败: {last_error}")

    def _request_upload_urls(self, parts: list[PdfPart], doc_id: str) -> tuple[str, list[str]]:
        payload = {
            "enable_formula": True,
            "enable_table": True,
            "language": "ch",
            "model_version": self.settings.mineru_model_version,
            "files": [
                {
                    "name": part.name,
                    "data_id": f"{doc_id}-p{index + 1}",
                    "is_ocr": self.settings.mineru_is_ocr,
                }
                for index, part in enumerate(parts)
            ],
        }
        result = self._request_json(
            "POST", f"{self.base_url}/file-urls/batch",
            headers={"Content-Type": "application/json"}, json=payload,
        )
        data = result.get("data") or {}
        batch_id = data.get("batch_id")
        urls = data.get("file_urls") or []
        if not batch_id or len(urls) != len(parts):
            raise MinerUError(f"申请上传链接返回异常: {result}")
        return str(batch_id), [str(url) for url in urls]

    def _upload_parts(self, parts: list[PdfPart], urls: list[str]) -> None:
        with httpx.Client(timeout=self.settings.mineru_timeout, follow_redirects=True) as client:
            for part, url in zip(parts, urls):
                with part.path.open("rb") as handle:
                    response = client.put(url, content=handle.read())
                if response.status_code not in (200, 201, 204):
                    raise MinerUError(
                        f"上传 {part.name} 失败: HTTP {response.status_code} {response.text[:200]}"
                    )

    def _wait_for_results(self, batch_id: str, expected: int) -> list[dict]:
        url = f"{self.base_url}/extract-results/batch/{batch_id}"
        max_polls = max(self.settings.mineru_max_polls, 60)
        interval = max(self.settings.mineru_poll_interval, 2)
        last_progress: dict[str, tuple[int, int]] = {}

        for _ in range(max_polls):
            payload = self._request_json("GET", url)
            data = payload.get("data") or {}
            results = data.get("extract_result") or data.get("extract_results") or []
            if len(results) < expected:
                time.sleep(interval)
                continue

            for item in results:
                name = item.get("file_name", "?")
                state = item.get("state", "?")
                progress = item.get("extract_progress") or {}
                key = (int(progress.get("extracted_pages") or 0),
                       int(progress.get("total_pages") or 0))
                if last_progress.get(name) != key:
                    last_progress[name] = key
                    if key[1]:
                        print(f"[mineru] {name}: {state} {key[0]}/{key[1]} 页", flush=True)
                    else:
                        print(f"[mineru] {name}: {state}", flush=True)

            failed = [item for item in results if item.get("state") == "failed"]
            if failed:
                reasons = "; ".join(
                    f"{item.get('file_name')}: {item.get('err_msg')}" for item in failed
                )
                raise MinerUError(f"MinerU 解析失败: {reasons}")

            if all(item.get("state") == "done" for item in results):
                return results

            time.sleep(interval)

        raise MinerUError(f"MinerU 轮询超时（batch_id={batch_id}）")

    def _download_results(
        self, parts: list[PdfPart], results: list[dict], doc_dir: Path
    ) -> list[ParsedPart]:
        by_name = {item.get("file_name"): item for item in results}
        mineru_dir = doc_dir / "mineru"
        mineru_dir.mkdir(parents=True, exist_ok=True)
        parsed: list[ParsedPart] = []

        for index, part in enumerate(parts):
            item = by_name.get(part.name) or results[index]
            zip_url = item.get("full_zip_url")
            if not zip_url:
                raise MinerUError(f"{part.name} 未返回 full_zip_url: {item}")

            zip_path = mineru_dir / f"part_{index + 1:02d}.zip"
            print(f"[mineru] 下载解析结果 {part.name} -> {zip_path.name}", flush=True)
            with httpx.Client(timeout=max(self.settings.mineru_timeout, 120), follow_redirects=True) as client:
                with client.stream("GET", zip_url) as response:
                    response.raise_for_status()
                    with zip_path.open("wb") as handle:
                        for chunk in response.iter_bytes():
                            handle.write(chunk)

            output_dir = mineru_dir / f"part_{index + 1:02d}"
            output_dir.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(zip_path) as archive:
                archive.extractall(output_dir)

            markdown_path = next(output_dir.rglob("full.md"), None)
            if markdown_path is None:
                raise MinerUError(f"{part.name} 的压缩包中未找到 full.md")
            content_list_path = next(
                (path for path in output_dir.rglob("*.json")
                 if path.name.endswith("content_list.json")),
                None,
            )
            parsed.append(
                ParsedPart(
                    part=part,
                    output_dir=output_dir,
                    markdown_path=markdown_path,
                    content_list_path=content_list_path,
                )
            )

        return parsed

    @staticmethod
    def _merge_markdown(parts: list[ParsedPart], output_path: Path) -> Path:
        sections: list[str] = []
        for index, parsed in enumerate(parts, start=1):
            part = parsed.part
            page_end = part.page_start + part.page_count - 1
            markdown = parsed.markdown_path.read_text(encoding="utf-8").strip()
            sections.append(
                f"<!-- part {index}: pages {part.page_start}-{page_end} -->\n\n{markdown}"
            )
        output_path.write_text("\n\n".join(sections), encoding="utf-8")
        return output_path
