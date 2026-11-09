from __future__ import annotations

import json
from pathlib import Path

import pytest

from zhibiao import pipeline
from zhibiao.mineru import MinerUError, MinerUResult, ParsedPart, PdfPart
from zhibiao.models import Block


def test_sha1_doc_id_and_page_count(make_pdf):
    pdf = make_pdf(pages=2)
    digest = pipeline.sha1_file(pdf)

    assert len(digest) == 40
    assert digest == pipeline.sha1_file(pdf)
    assert pipeline.make_doc_id(pdf, digest) == f"{pdf.stem}-{digest[:10]}"
    assert pipeline._page_count(pdf) == 2


def test_load_cached_blocks_valid_invalid(tmp_path):
    doc_dir = tmp_path / "doc"
    doc_dir.mkdir()
    assert pipeline._load_cached_blocks(doc_dir, "abc") is None

    markdown = tmp_path / "full.md"
    markdown.write_text("x", encoding="utf-8")
    (doc_dir / "blocks.json").write_text(
        json.dumps([{"text": "t", "page": 1, "type": "text", "level": 0}]),
        encoding="utf-8",
    )
    (doc_dir / "manifest.json").write_text(
        json.dumps(
            {"sha1": "abc", "markdown_path": str(markdown), "parser": "mineru"}
        ),
        encoding="utf-8",
    )

    cached = pipeline._load_cached_blocks(doc_dir, "abc")
    assert cached is not None
    assert cached[1][0].text == "t"
    assert cached[2] == "mineru"
    assert pipeline._load_cached_blocks(doc_dir, "other") is None


def test_parse_document_reuses_cache(settings, make_pdf, monkeypatch):
    pdf = make_pdf()
    sha1 = pipeline.sha1_file(pdf)
    doc_id = pipeline.make_doc_id(pdf, sha1)
    doc_dir = settings.data_dir / "parsed" / doc_id
    doc_dir.mkdir(parents=True)
    markdown = doc_dir / "full.md"
    markdown.write_text("cached", encoding="utf-8")
    (doc_dir / "blocks.json").write_text(
        json.dumps([{"text": "缓存标题", "page": 1, "type": "text", "level": 1}]),
        encoding="utf-8",
    )
    (doc_dir / "manifest.json").write_text(
        json.dumps(
            {"sha1": sha1, "markdown_path": str(markdown), "parser": "mineru"}
        ),
        encoding="utf-8",
    )

    class ExplodingParser:
        def __init__(self, *args, **kwargs):
            raise AssertionError("should not call MinerU when cache is valid")

    monkeypatch.setattr(pipeline, "MinerUCloudParser", ExplodingParser)

    got_id, got_dir, got_md, blocks, parser_used = pipeline.parse_document(pdf, settings)

    assert got_id == doc_id
    assert got_dir == doc_dir
    assert got_md == markdown
    assert blocks[0].text == "缓存标题"
    assert parser_used == "mineru"


def test_parse_document_mineru_success(settings, make_pdf, monkeypatch):
    pdf = make_pdf(pages=2)

    class FakeParser:
        def __init__(self, *args, **kwargs):
            pass

        def parse(self, pdf_path, doc_id, doc_dir):
            doc_dir.mkdir(parents=True, exist_ok=True)
            markdown = doc_dir / "full.md"
            markdown.write_text("## 标题\n\n正文", encoding="utf-8")
            content_list = doc_dir / "x_content_list.json"
            content_list.write_text(
                json.dumps([
                    {"type": "text", "text": "标题", "page_idx": 0, "text_level": 1},
                    {"type": "text", "text": "正文", "page_idx": 1},
                ]),
                encoding="utf-8",
            )
            part = PdfPart(pdf_path, pdf_path.name, 1, 2, 0)
            return MinerUResult(
                doc_dir=doc_dir,
                parts=[
                    ParsedPart(
                        part=part,
                        output_dir=doc_dir,
                        markdown_path=markdown,
                        content_list_path=content_list,
                    )
                ],
                combined_markdown=markdown,
            )

    monkeypatch.setattr(pipeline, "MinerUCloudParser", FakeParser)

    _, doc_dir, _, blocks, parser_used = pipeline.parse_document(pdf, settings)

    assert parser_used == "mineru"
    assert [block.page for block in blocks] == [1, 2]
    assert (doc_dir / "manifest.json").exists()
    assert (doc_dir / "blocks.json").exists()


def test_parse_document_fallback_and_strict_mode(settings, make_pdf, monkeypatch):
    pdf = make_pdf(pages=2)

    class BrokenParser:
        def __init__(self, *args, **kwargs):
            pass

        def parse(self, *args, **kwargs):
            raise MinerUError("cloud down")

    monkeypatch.setattr(pipeline, "MinerUCloudParser", BrokenParser)

    _, _, _, blocks, parser_used = pipeline.parse_document(pdf, settings)
    assert parser_used == "pymupdf"
    assert blocks

    with pytest.raises(MinerUError):
        pipeline.parse_document(pdf, settings, parser="mineru", reparse=True)


def test_parse_pdf_to_chunks(settings, make_pdf, tmp_path, monkeypatch):
    pdf = make_pdf()
    doc_dir = tmp_path / "doc"
    doc_dir.mkdir()
    (doc_dir / "manifest.json").write_text(
        json.dumps({"page_count": 2}), encoding="utf-8"
    )
    blocks = [
        Block("第一章 招标公告", page=1, type="heading", level=1),
        Block("正文" * 100, page=1),
    ]
    monkeypatch.setattr(
        pipeline,
        "parse_document",
        lambda *args, **kwargs: ("doc-1", doc_dir, tmp_path / "full.md", blocks, "mineru"),
    )

    result = pipeline.parse_pdf_to_chunks(pdf, settings, filename="original.pdf")

    assert result["doc_id"] == "doc-1"
    assert result["filename"] == "original.pdf"
    assert result["page_count"] == 2
    assert result["parser"] == "mineru"
    assert result["chunk_count"] > 0
    assert result["chunks_preview"]
    assert (doc_dir / "chunks.jsonl").exists()


def test_ingest_dry_run(settings, make_pdf, tmp_path, monkeypatch):
    pdf = make_pdf()
    doc_dir = tmp_path / "doc"
    doc_dir.mkdir()
    blocks = [Block("第一章 招标公告", page=1, type="heading", level=1), Block("正文" * 100, page=1)]
    monkeypatch.setattr(
        pipeline,
        "parse_document",
        lambda *args, **kwargs: ("doc-1", doc_dir, tmp_path / "full.md", blocks, "mineru"),
    )

    class NoEmbedder:
        def __init__(self, *args, **kwargs):
            raise AssertionError("dry-run should not embed")

    monkeypatch.setattr(pipeline, "ZhipuEmbedder", NoEmbedder)

    pipeline.ingest_pdf(pdf, settings, dry_run=True)

    lines = (doc_dir / "chunks.jsonl").read_text(encoding="utf-8").splitlines()
    assert lines
    assert json.loads(lines[0])["text"]


def test_ingest_full_and_search(settings, make_pdf, tmp_path, monkeypatch, capsys):
    pdf = make_pdf()
    doc_dir = tmp_path / "doc"
    doc_dir.mkdir()
    blocks = [Block("第一章 招标公告", page=1, type="heading", level=1), Block("正文" * 100, page=1)]
    monkeypatch.setattr(
        pipeline,
        "parse_document",
        lambda *args, **kwargs: ("doc-1", doc_dir, tmp_path / "full.md", blocks, "mineru"),
    )

    store_calls = []

    class FakeEmbedder:
        def __init__(self, *args, **kwargs):
            pass

        def embed_documents(self, texts, progress=None):
            if progress:
                progress(len(texts), len(texts))
            return [[0.1, 0.2] for _ in texts]

        def embed_query(self, query):
            return [0.1, 0.2]

    class FakeStore:
        def __init__(self, *args, **kwargs):
            pass

        def replace_document(self, **kwargs):
            store_calls.append(kwargs)

        def count(self):
            return 1

        def query(self, embedding, n_results=8, where=None):
            return {
                "documents": [["内容"]],
                "metadatas": [[
                    {"heading": "章节", "page_start": 1, "page_end": 2, "source": "doc.pdf"}
                ]],
                "distances": [[0.2]],
            }

    monkeypatch.setattr(pipeline, "ZhipuEmbedder", FakeEmbedder)
    monkeypatch.setattr(pipeline, "ChunkStore", FakeStore)

    pipeline.ingest_pdf(pdf, settings)

    assert store_calls and store_calls[0]["doc_id"] == "doc-1"
    assert store_calls[0]["parser"] == "mineru"

    class FakeRetriever:
        def __init__(self, *args, **kwargs):
            pass

        def search(self, query, n_results=5, intent=None):
            return {
                "query": query,
                "intent": "general",
                "strategy": {},
                "candidate_count": 1,
                "took_ms": 1,
                "results": [
                    {
                        "id": "doc-1:00000",
                        "doc_id": "doc-1",
                        "text": "内容",
                        "snippet": "内容",
                        "heading": "章节",
                        "page_start": 1,
                        "page_end": 2,
                        "source": "doc.pdf",
                        "type": "text",
                        "table_id": "",
                        "tags": [],
                        "score": 0.9,
                        "keyword_score": 0.8,
                        "vector_score": 0.7,
                        "forced": False,
                        "reasons": ["bm25", "vector"],
                    }
                ],
            }

    monkeypatch.setattr(pipeline, "HybridRetriever", FakeRetriever)

    result = pipeline.search("投标保证金", settings)
    assert result["results"][0]["heading"] == "章节"
    assert "章节" in capsys.readouterr().out

    class EmptyRetriever:
        def __init__(self, *args, **kwargs):
            pass

        def search(self, query, n_results=5, intent=None):
            raise RuntimeError("向量库为空，请先执行 ingest")

    monkeypatch.setattr(pipeline, "HybridRetriever", EmptyRetriever)
    with pytest.raises(RuntimeError, match="向量库为空"):
        pipeline.search("q", settings)
