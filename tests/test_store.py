from __future__ import annotations

import pytest

from zhibiao import store as store_module
from zhibiao.models import Chunk
from zhibiao.store import ChunkStore


class FakeCollection:
    def __init__(self):
        self.deleted = []
        self.upserts = []
        self.query_kwargs = None
        self.stored = {"ids": [], "documents": [], "metadatas": []}
        self.updates = []

    def delete(self, where):
        self.deleted.append(where)

    def upsert(self, **kwargs):
        self.upserts.append(kwargs)

    def get(self, include=None):
        return {
            "ids": list(self.stored["ids"]),
            "documents": list(self.stored["documents"]),
            "metadatas": [dict(item) for item in self.stored["metadatas"]],
        }

    def update(self, ids, metadatas):
        self.updates.append((list(ids), [dict(item) for item in metadatas]))
        by_id = {
            chunk_id: dict(metadata)
            for chunk_id, metadata in zip(
                self.stored["ids"], self.stored["metadatas"]
            )
        }
        for chunk_id, metadata in zip(ids, metadatas):
            by_id[chunk_id] = dict(metadata)
        self.stored["metadatas"] = [
            by_id[chunk_id] for chunk_id in self.stored["ids"]
        ]

    def query(self, **kwargs):
        self.query_kwargs = kwargs
        return {
            "ids": [["doc-1:00000"]],
            "documents": [["doc"]],
            "metadatas": [[{"heading": "h", "page_start": 1, "page_end": 1}]],
            "distances": [[0.1]],
        }

    def count(self):
        return 42


class FakeClient:
    def __init__(self, *args, **kwargs):
        self.collection = FakeCollection()

    def get_or_create_collection(self, name, configuration=None):
        self.name = name
        self.configuration = configuration
        return self.collection


def install_fake_client(monkeypatch):
    created = {}

    class Client(FakeClient):
        def __init__(self, *args, **kwargs):
            super().__init__()
            created["client"] = self

    monkeypatch.setattr("zhibiao.store.chromadb.PersistentClient", Client)
    return created


def test_constructor_configures_cosine(monkeypatch, tmp_path):
    created = install_fake_client(monkeypatch)

    ChunkStore(tmp_path / "chroma", "bid_documents")

    client = created["client"]
    assert client.name == "bid_documents"
    assert client.configuration == {"hnsw": {"space": "cosine"}}


def test_replace_document_deletes_and_upserts_metadata(monkeypatch, tmp_path):
    install_fake_client(monkeypatch)
    store = ChunkStore(tmp_path / "chroma", "col")
    collection = store.client.collection
    chunks = [
        Chunk("text1", page_start=1, page_end=2, heading="head", block_types="text,table"),
        Chunk("x" * 600, page_start=3, page_end=4, heading="h" * 600, block_types="text"),
    ]

    count = store.replace_document(
        "doc-abc", chunks, [[0.1], [0.2]], "src.pdf", "mineru"
    )

    assert count == 2
    assert collection.deleted == [{"doc_id": "doc-abc"}]
    assert len(collection.upserts) == 1
    upsert = collection.upserts[0]
    assert upsert["ids"] == ["doc-abc:00000", "doc-abc:00001"]
    assert upsert["documents"] == [chunk.text for chunk in chunks]
    assert upsert["embeddings"] == [[0.1], [0.2]]
    metadata = upsert["metadatas"][0]
    assert metadata["doc_id"] == "doc-abc"
    assert metadata["source"] == "src.pdf"
    assert metadata["parser"] == "mineru"
    assert metadata["chunk_index"] == 0
    assert metadata["page_start"] == 1
    assert metadata["page_end"] == 2
    assert metadata["block_types"] == "text,table"
    assert metadata["type"] == "table"
    assert metadata["table_id"].startswith("legacy-doc-abc:")
    assert metadata["qualification"] is False
    assert len(upsert["metadatas"][1]["heading"]) == 500


def test_replace_document_batches_tolerates_delete_error_and_rejects_mismatch(
    monkeypatch, tmp_path, capsys
):
    install_fake_client(monkeypatch)
    monkeypatch.setattr(store_module, "UPSERT_BATCH_SIZE", 2)
    store = ChunkStore(tmp_path / "chroma", "col")
    collection = store.client.collection

    def fail_delete(where):
        raise RuntimeError("empty collection")

    collection.delete = fail_delete
    chunks = [Chunk(f"text{i}", page_start=i, page_end=i) for i in range(5)]

    assert store.replace_document(
        "doc", chunks, [[float(i)] for i in range(5)], "src", "mineru"
    ) == 5
    assert len(collection.upserts) == 3
    assert [len(batch["ids"]) for batch in collection.upserts] == [2, 2, 1]
    assert "清理旧片段失败" in capsys.readouterr().out

    with pytest.raises(ValueError):
        store.replace_document("doc", chunks[:1], [[0.0], [0.1]], "src", "mineru")


def test_table_and_qualification_metadata(monkeypatch, tmp_path):
    install_fake_client(monkeypatch)
    store = ChunkStore(tmp_path / "chroma", "col")
    chunks = [
        Chunk(
            "资格审查资料：营业执照、安全生产许可证",
            page_start=1,
            page_end=1,
            heading="第三章 资格审查",
            block_types="table",
            table_id="table-p1-001",
        )
    ]

    store.replace_document(
        "doc-qual", chunks, [[0.1]], "src.pdf", "mineru"
    )

    metadata = store.client.collection.upserts[0]["metadatas"][0]
    assert metadata["type"] == "table"
    assert metadata["table_id"] == "table-p1-001"
    assert "资格审查" in metadata["tags"]
    assert metadata["qualification"] is True


def test_backfill_metadata_for_legacy_chunks(monkeypatch, tmp_path):
    install_fake_client(monkeypatch)
    store = ChunkStore(tmp_path / "chroma", "col")
    collection = store.client.collection
    collection.stored = {
        "ids": ["doc:00000", "doc:00001"],
        "documents": [
            "资格审查 营业执照 业绩",
            "施工组织设计 编制方案",
        ],
        "metadatas": [
            {"block_types": "table", "heading": "第三章 资格审查"},
            {"block_types": "text", "heading": "第七章 施工组织设计"},
        ],
    }

    count = store.backfill_metadata()

    assert count == 2
    assert collection.updates
    first = collection.stored["metadatas"][0]
    assert first["type"] == "table"
    assert first["table_id"] == "legacy-doc:00000"
    assert "资格审查" in first["tags"]
    assert first["qualification"] is True
    second = collection.stored["metadatas"][1]
    assert second["type"] == "text"
    assert "章节写法" in second["tags"]


def test_all_chunks_and_query_and_count(monkeypatch, tmp_path):
    install_fake_client(monkeypatch)
    store = ChunkStore(tmp_path / "chroma", "col")
    store.client.collection.stored = {
        "ids": ["doc-1:00000"],
        "documents": ["doc"],
        "metadatas": [{"heading": "h"}],
    }

    all_chunks = store.all_chunks()
    assert all_chunks["ids"] == ["doc-1:00000"]

    result = store.query([0.1, 0.2], n_results=3, where={"doc_id": "doc"})

    assert result["documents"] == [["doc"]]
    kwargs = store.client.collection.query_kwargs
    assert kwargs["query_embeddings"] == [[0.1, 0.2]]
    assert kwargs["n_results"] == 3
    assert kwargs["where"] == {"doc_id": "doc"}
    assert kwargs["include"] == ["documents", "metadatas", "distances"]
    assert store.count() == 42
