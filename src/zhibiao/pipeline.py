from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import pymupdf
from langsmith import traceable

from .chunker import chunk_blocks
from .config import Settings, get_settings
from .content_list import blocks_from_content_list, blocks_from_markdown
from .embedder import ZhipuEmbedder
from .fallback import parse_with_pymupdf
from .mineru import MinerUCloudParser
from .models import Block, Chunk
from .retrieval import HybridRetriever
from .store import ChunkStore


def sha1_file(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def make_doc_id(pdf_path: Path, sha1: str) -> str:
    return f"{pdf_path.stem}-{sha1[:10]}"


def _page_count(pdf_path: Path) -> int:
    with pymupdf.open(pdf_path) as doc:
        return doc.page_count


def write_chunks_jsonl(chunks: list[Chunk], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for index, chunk in enumerate(chunks):
            handle.write(
                json.dumps(
                    {
                        "index": index,
                        "page_start": chunk.page_start,
                        "page_end": chunk.page_end,
                        "heading": chunk.heading,
                        "block_types": chunk.block_types,
                        "table_id": chunk.table_id,
                        "text": chunk.text,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )


def _load_cached_blocks(doc_dir: Path, sha1: str) -> tuple[Path, list[Block], str] | None:
    manifest_path = doc_dir / "manifest.json"
    blocks_path = doc_dir / "blocks.json"
    if not manifest_path.exists() or not blocks_path.exists():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("sha1") != sha1:
            return None
        blocks = [Block(**item) for item in json.loads(blocks_path.read_text(encoding="utf-8"))]
        return Path(manifest["markdown_path"]), blocks, str(manifest["parser"])
    except (KeyError, TypeError, ValueError):
        return None


def parse_document(
    pdf_path: Path,
    settings: Settings,
    parser: str = "auto",
    reparse: bool = False,
) -> tuple[str, Path, Path, list[Block], str]:
    """解析 PDF 为带页码的 Markdown 块；结果缓存在 data/parsed/<doc_id>/。"""
    sha1 = sha1_file(pdf_path)
    doc_id = make_doc_id(pdf_path, sha1)
    doc_dir = settings.data_dir / "parsed" / doc_id
    doc_dir.mkdir(parents=True, exist_ok=True)

    if not reparse:
        cached = _load_cached_blocks(doc_dir, sha1)
        if cached:
            markdown_path, blocks, cached_parser = cached
            if parser == "auto" or parser == cached_parser:
                print(f"[parse] 复用缓存 {doc_dir}（parser={cached_parser}）", flush=True)
                return doc_id, doc_dir, markdown_path, blocks, cached_parser

    markdown_path: Path | None = None
    blocks: list[Block] = []
    parser_used = ""
    mineru_error: Exception | None = None

    if parser in ("auto", "mineru") and settings.mineru_enabled:
        try:
            mineru = MinerUCloudParser(settings)
            result = mineru.parse(pdf_path, sha1[:16], doc_dir)
            for parsed_part in result.parts:
                part = parsed_part.part
                if parsed_part.content_list_path:
                    items = json.loads(
                        parsed_part.content_list_path.read_text(encoding="utf-8")
                    )
                    blocks.extend(
                        blocks_from_content_list(items, page_offset=part.page_offset)
                    )
                else:
                    markdown = parsed_part.markdown_path.read_text(encoding="utf-8")
                    blocks.extend(blocks_from_markdown(markdown, page_start=part.page_start))
            markdown_path = result.combined_markdown
            parser_used = "mineru"
        except Exception as exc:  # noqa: BLE001 - 解析失败时回退
            mineru_error = exc
            if parser == "mineru":
                raise
            print(f"[warn] MinerU 解析失败，回退 PyMuPDF: {exc}", flush=True)

    if markdown_path is None:
        markdown_path, blocks = parse_with_pymupdf(pdf_path, doc_dir)
        parser_used = "pymupdf"
    elif mineru_error is not None:
        print(f"[warn] MinerU 错误: {mineru_error}", flush=True)

    if not blocks:
        raise RuntimeError("解析后没有任何文本块，无法入库")

    manifest = {
        "doc_id": doc_id,
        "source": str(pdf_path.resolve()),
        "sha1": sha1,
        "page_count": _page_count(pdf_path),
        "parser": parser_used,
        "markdown_path": str(markdown_path),
        "block_count": len(blocks),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    (doc_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (doc_dir / "blocks.json").write_text(
        json.dumps([asdict(block) for block in blocks], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return doc_id, doc_dir, markdown_path, blocks, parser_used


@traceable(name="parse.pdf", run_type="chain")
def parse_pdf_to_chunks(
    pdf_path: Path,
    settings: Settings | None = None,
    parser: str = "auto",
    filename: str | None = None,
) -> dict:
    """解析 PDF + 分块并写出 chunks.jsonl，返回可 JSON 序列化的任务结果。"""
    pdf_path = pdf_path.resolve()
    if not pdf_path.exists():
        raise FileNotFoundError(f"文件不存在: {pdf_path}")
    settings = settings or get_settings()

    doc_id, doc_dir, markdown_path, blocks, parser_used = parse_document(
        pdf_path, settings, parser=parser
    )
    chunks = chunk_blocks(
        blocks,
        max_chars=settings.chunk_max_chars,
        overlap=settings.chunk_overlap,
    )
    if not chunks:
        raise RuntimeError("分块后没有任何片段")

    chunks_path = doc_dir / "chunks.jsonl"
    write_chunks_jsonl(chunks, chunks_path)
    manifest = json.loads((doc_dir / "manifest.json").read_text(encoding="utf-8"))
    return {
        "doc_id": doc_id,
        "filename": filename or pdf_path.name,
        "page_count": int(manifest.get("page_count") or 0),
        "parser": parser_used,
        "block_count": len(blocks),
        "chunk_count": len(chunks),
        "markdown_path": str(markdown_path),
        "chunks_path": str(chunks_path),
        "chunks_preview": [
            {
                "index": index,
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
                "heading": chunk.heading[:200],
                "text": chunk.text[:300],
            }
            for index, chunk in enumerate(chunks[:3])
        ],
    }


@traceable(name="ingest.pdf", run_type="chain")
def ingest_pdf(
    pdf_path: Path,
    settings: Settings,
    parser: str = "auto",
    reparse: bool = False,
    max_chars: int | None = None,
    overlap: int | None = None,
    dry_run: bool = False,
) -> None:
    pdf_path = pdf_path.resolve()
    if not pdf_path.exists():
        raise FileNotFoundError(f"文件不存在: {pdf_path}")

    doc_id, doc_dir, markdown_path, blocks, parser_used = parse_document(
        pdf_path, settings, parser=parser, reparse=reparse
    )
    chunks = chunk_blocks(
        blocks,
        max_chars=max_chars or settings.chunk_max_chars,
        overlap=settings.chunk_overlap if overlap is None else overlap,
    )
    if not chunks:
        raise RuntimeError("分块后没有任何片段")

    chunks_path = doc_dir / "chunks.jsonl"
    write_chunks_jsonl(chunks, chunks_path)

    total_chars = sum(len(chunk.text) for chunk in chunks)
    print(
        f"[chunk] parser={parser_used} blocks={len(blocks)} chunks={len(chunks)} "
        f"avg_chars={total_chars // len(chunks)} markdown={markdown_path}",
        flush=True,
    )
    print(f"[chunk] 明细: {chunks_path}", flush=True)

    if dry_run:
        print("[dry-run] 跳过 embedding 与 Chroma 写入", flush=True)
        return

    embedder = ZhipuEmbedder(
        api_key=settings.zhipu_api_key,
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
    )
    print(f"[embed] 调用智谱 {settings.embedding_model} 嵌入 {len(chunks)} 个片段…", flush=True)
    embeddings = embedder.embed_documents(
        [chunk.text for chunk in chunks],
        progress=lambda done, total: print(f"[embed] {done}/{total}", flush=True),
    )

    store = ChunkStore(settings.chroma_dir, settings.chroma_collection)
    print(f"[store] 写入 Chroma: {settings.chroma_dir} / {settings.chroma_collection}", flush=True)
    store.replace_document(
        doc_id=doc_id,
        chunks=chunks,
        embeddings=embeddings,
        source=pdf_path.name,
        parser=parser_used,
    )
    print(f"[done] doc_id={doc_id} 已入库，collection 共 {store.count()} 个片段", flush=True)


@traceable(name="search", run_type="chain")
def search(
    query: str,
    settings: Settings,
    n_results: int = 5,
    intent: str | None = None,
) -> dict:
    retriever = HybridRetriever(settings)
    result = retriever.search(query, n_results=n_results, intent=intent)
    print(
        f"[search] intent={result['intent']} candidates={result['candidate_count']} "
        f"took={result['took_ms']}ms",
        flush=True,
    )
    for index, item in enumerate(result["results"], start=1):
        tags = ",".join(item["tags"]) or "-"
        print(
            f"\n[{index}] score={item['score']:.4f} type={item['type']} "
            f"tags={tags} "
            f"pages={item['page_start']}-{item['page_end']} "
            f"source={item['source']}",
            flush=True,
        )
        print(f"    章节: {item['heading'] or '（无章节）'}", flush=True)
        if item["table_id"]:
            print(f"    表格: {item['table_id']}", flush=True)
        print(f"    内容: {item['snippet']}…", flush=True)
    return result
