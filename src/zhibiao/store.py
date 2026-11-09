from __future__ import annotations

from pathlib import Path

import chromadb
from chromadb.config import Settings as ChromaSettings
from langsmith import traceable

from .metadata import chunk_metadata, normalize_metadata
from .models import Chunk

UPSERT_BATCH_SIZE = 256


class ChunkStore:
    def __init__(self, persist_dir: Path, collection_name: str) -> None:
        persist_dir.mkdir(parents=True, exist_ok=True)
        self.persist_dir = persist_dir
        self.collection_name = collection_name
        self.client = chromadb.PersistentClient(
            path=str(persist_dir),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            configuration={"hnsw": {"space": "cosine"}},
        )

    @traceable(name="chroma.replace_document", run_type="tool")
    def replace_document(
        self,
        doc_id: str,
        chunks: list[Chunk],
        embeddings: list[list[float]],
        source: str,
        parser: str,
    ) -> int:
        """按 doc_id 覆盖写入，保证重复入库不产生旧片段。"""
        if len(chunks) != len(embeddings):
            raise ValueError(f"片段与向量数量不一致: {len(chunks)} != {len(embeddings)}")

        try:
            self.collection.delete(where={"doc_id": doc_id})
        except Exception as exc:  # noqa: BLE001 - 空集合删除会报错
            print(f"[warn] 清理旧片段失败（可忽略）: {exc}", flush=True)

        ids = [f"{doc_id}:{index:05d}" for index in range(len(chunks))]
        metadatas = []
        for index, chunk in enumerate(chunks):
            metadata = {
                "doc_id": doc_id,
                "source": source,
                "parser": parser,
                "chunk_index": index,
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
                "heading": chunk.heading[:500],
                "block_types": chunk.block_types,
            }
            metadata.update(
                chunk_metadata(
                    chunk.text,
                    chunk.heading,
                    chunk.block_types,
                    chunk.table_id,
                )
            )
            metadatas.append(normalize_metadata(ids[index], chunk.text, metadata))

        for start in range(0, len(chunks), UPSERT_BATCH_SIZE):
            end = start + UPSERT_BATCH_SIZE
            self.collection.upsert(
                ids=ids[start:end],
                embeddings=embeddings[start:end],
                documents=[chunk.text for chunk in chunks[start:end]],
                metadatas=metadatas[start:end],
            )
        return len(chunks)

    @traceable(
        name="chroma.list_chunks",
        run_type="retriever",
        process_outputs=lambda output: {
            "count": len(output.get("ids") or []),
            "with_embeddings": output.get("embeddings") is not None,
        },
    )
    def all_chunks(self, include_embeddings: bool = False) -> dict:
        """读取全部片段，供 BM25 建索引；本地知识库规模通常很小。"""
        include = ["documents", "metadatas"]
        if include_embeddings:
            include.append("embeddings")
        return self.collection.get(include=include)

    @traceable(name="chroma.query", run_type="retriever")
    def query(
        self,
        embedding: list[float],
        n_results: int = 8,
        where: dict | None = None,
    ) -> dict:
        return self.collection.query(
            query_embeddings=[embedding],
            n_results=n_results,
            where=where,
            include=["documents", "metadatas", "distances"],
        )

    @traceable(name="chroma.backfill_metadata", run_type="tool")
    def backfill_metadata(self) -> int:
        """为已有 collection 回填 type/table_id/tags 等检索元数据。"""
        data = self.all_chunks()
        ids = data.get("ids") or []
        documents = data.get("documents") or []
        metadatas = data.get("metadatas") or []
        updates: list[tuple[str, dict]] = []
        for chunk_id, text, metadata in zip(ids, documents, metadatas):
            normalized = normalize_metadata(chunk_id, text or "", metadata)
            if normalized != metadata:
                updates.append((chunk_id, normalized))

        for start in range(0, len(updates), UPSERT_BATCH_SIZE):
            batch = updates[start:start + UPSERT_BATCH_SIZE]
            self.collection.update(
                ids=[chunk_id for chunk_id, _ in batch],
                metadatas=[metadata for _, metadata in batch],
            )
        return len(ids)

    def count(self) -> int:
        return self.collection.count()
