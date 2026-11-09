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

    def delete(self, where):
        self.deleted.append(where)

    def upsert(self, **kwargs):
        self.upserts.append(kwargs)

    def query(self, **kwargs):
        self.query_kwargs = kwargs
        return {
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


def test_query_and_count(monkeypatch, tmp_path):
    install_fake_client(monkeypatch)
    store = ChunkStore(tmp_path / "chroma", "col")

    result = store.query([0.1, 0.2], n_results=3, where={"doc_id": "doc"})

    assert result["documents"] == [["doc"]]
    kwargs = store.client.collection.query_kwargs
    assert kwargs["query_embeddings"] == [[0.1, 0.2]]
    assert kwargs["n_results"] == 3
    assert kwargs["where"] == {"doc_id": "doc"}
    assert kwargs["include"] == ["documents", "metadatas", "distances"]
    assert store.count() == 42
