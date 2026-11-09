from __future__ import annotations

import pytest

from zhibiao.retrieval import HybridRetriever, detect_intent, tokenize

ROWS = [
    (
        "c-qual",
        "资格审查资料包括营业执照、安全生产许可证和类似业绩。",
        {
            "doc_id": "doc1",
            "heading": "第三章 资格审查",
            "block_types": "text",
            "page_start": 10,
            "page_end": 10,
            "source": "a.pdf",
        },
    ),
    (
        "c-table",
        "投标报价计算公式：综合单价=人工费+材料费+机械费。",
        {
            "doc_id": "doc1",
            "heading": "第五章 投标报价",
            "block_types": "table",
            "table_id": "table-p5-001",
            "page_start": 20,
            "page_end": 20,
            "source": "a.pdf",
        },
    ),
    (
        "c-section",
        "施工组织设计应包含工程概况、施工方案、质量保证措施。",
        {
            "doc_id": "doc1",
            "heading": "第七章 施工组织设计",
            "block_types": "text",
            "page_start": 30,
            "page_end": 30,
            "source": "a.pdf",
        },
    ),
    (
        "c-general",
        "其他说明。",
        {
            "doc_id": "doc1",
            "heading": "第一章 总则",
            "block_types": "text",
            "page_start": 1,
            "page_end": 1,
            "source": "a.pdf",
        },
    ),
]


class FakeStore:
    def __init__(self, vector_ids: list[str] | None = None) -> None:
        self.vector_ids = vector_ids or []
        self.query_calls = []

    def all_chunks(self) -> dict:
        return {
            "ids": [row[0] for row in ROWS],
            "documents": [row[1] for row in ROWS],
            "metadatas": [dict(row[2]) for row in ROWS],
        }

    def query(self, embedding, n_results=8, where=None) -> dict:
        self.query_calls.append((embedding, n_results, where))
        by_id = {row[0]: row for row in ROWS}
        ids = [chunk_id for chunk_id in self.vector_ids if chunk_id in by_id][:n_results]
        return {
            "ids": [ids],
            "documents": [[by_id[chunk_id][1] for chunk_id in ids]],
            "metadatas": [[dict(by_id[chunk_id][2]) for chunk_id in ids]],
            "distances": [[0.1 + index * 0.05 for index, _ in enumerate(ids)]],
        }


class EmptyStore:
    def all_chunks(self) -> dict:
        return {"ids": [], "documents": [], "metadatas": []}


class FakeEmbedder:
    def embed_query(self, query: str) -> list[float]:
        return [0.1, 0.2]


def make_retriever(settings, vector_ids=None, embedder=None) -> HybridRetriever:
    return HybridRetriever(
        settings,
        store=FakeStore(vector_ids=vector_ids),
        embedder=embedder or FakeEmbedder(),
    )


def test_intent_detection():
    assert detect_intent("资格审查需要哪些材料") == "qualification"
    assert detect_intent("投标报价计算公式") == "formula"
    assert detect_intent("施工组织设计怎么写") == "section_writing"
    assert detect_intent("今天天气怎么样") == "general"


def test_chinese_bigram_tokenization():
    tokens = tokenize("资格审查 ABC-123")

    assert "资格" in tokens
    assert "审查" in tokens
    assert "abc" in tokens
    assert "123" in tokens


def test_formula_query_prefers_table(settings):
    result = make_retriever(settings, vector_ids=["c-general"]).search(
        "投标报价计算公式", n_results=3
    )

    assert result["intent"] == "formula"
    assert result["results"][0]["id"] == "c-table"
    assert result["results"][0]["type"] == "table"
    assert result["results"][0]["table_id"] == "table-p5-001"
    assert "bm25_table" in result["results"][0]["reasons"]


def test_section_query_prefers_heading(settings):
    result = make_retriever(settings).search("施工组织设计怎么写", n_results=3)

    assert result["intent"] == "section_writing"
    assert result["results"][0]["id"] == "c-section"
    assert "bm25_heading" in result["results"][0]["reasons"]


def test_qualification_intent_force_recalls_tagged_chunks(settings):
    result = make_retriever(settings, vector_ids=["c-general"]).search(
        "资格审查需要哪些材料", n_results=3
    )

    assert result["intent"] == "qualification"
    assert result["results"][0]["id"] == "c-qual"
    assert result["results"][0]["forced"] is True
    assert "资格审查" in result["results"][0]["tags"]
    assert result["strategy"]["forced_qualification"] >= 1


def test_vector_supplement_when_keyword_has_no_match(settings):
    result = make_retriever(settings, vector_ids=["c-general"]).search(
        "完全无关的查询词", n_results=3
    )

    assert result["results"]
    assert result["results"][0]["id"] == "c-general"
    assert "vector" in result["results"][0]["reasons"]


def test_dense_prefix_scan_uses_fast_query_dimensions(settings):
    class DenseStore(FakeStore):
        def all_chunks(self, include_embeddings: bool = False) -> dict:
            data = super().all_chunks()
            if include_embeddings:
                embeddings = []
                for row in ROWS:
                    vector = [0.0] * 1024
                    vector[0] = 1.0 if row[0] == "c-general" else 0.1
                    if row[0] != "c-general":
                        vector[1] = 1.0
                    embeddings.append(vector)
                data["embeddings"] = embeddings
            return data

    class DimensionEmbedder:
        def __init__(self):
            self.dimensions = None

        def embed_query(self, query, dimensions=None):
            self.dimensions = dimensions
            vector = [0.0] * (dimensions or 1024)
            vector[0] = 1.0
            return vector

    store = DenseStore()
    embedder = DimensionEmbedder()
    retriever = HybridRetriever(settings, store=store, embedder=embedder)
    result = retriever.search("完全无关的查询词", n_results=2)

    assert embedder.dimensions == 768
    assert store.query_calls == []
    assert result["results"][0]["id"] == "c-general"
    assert result["results"][0]["vector_score"] is not None


def test_keyword_fallback_when_embedding_unavailable(settings):
    class BrokenEmbedder:
        def embed_query(self, query: str) -> list[float]:
            raise RuntimeError("embedding down")

    retriever = HybridRetriever(
        settings,
        store=FakeStore(vector_ids=["c-general"]),
        embedder=BrokenEmbedder(),
    )
    result = retriever.search("资格审查", n_results=3)

    assert result["strategy"]["vector_error"]
    assert any(item["id"] == "c-qual" for item in result["results"])


def test_empty_store_raises(settings):
    retriever = HybridRetriever(
        settings, store=EmptyStore(), embedder=FakeEmbedder()
    )

    with pytest.raises(RuntimeError, match="向量库为空"):
        retriever.search("资格审查")
