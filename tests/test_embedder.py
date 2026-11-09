from __future__ import annotations

import pytest

from zhibiao.embedder import EmbeddingError, ZhipuEmbedder


class FakeEmbedding:
    def __init__(self, embedding, index):
        self.embedding = embedding
        self.index = index


class FakeEmbeddingResponse:
    def __init__(self, vectors):
        self.data = [FakeEmbedding(vector, index) for index, vector in enumerate(vectors)]


class AuthError(Exception):
    status_code = 401


def install_fake_client(monkeypatch, responses, calls):
    class FakeEmbeddings:
        def create(self, **kwargs):
            calls.append(kwargs)
            item = responses.pop(0)
            if isinstance(item, BaseException):
                raise item
            return FakeEmbeddingResponse(item)

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.embeddings = FakeEmbeddings()

    monkeypatch.setattr("zhibiao.embedder.ZhipuAiClient", FakeClient)


def test_init_requires_api_key():
    with pytest.raises(EmbeddingError):
        ZhipuEmbedder("")


def test_embed_documents_batches_and_progress(monkeypatch):
    calls = []
    responses = [[[0.1], [0.2]], [[0.3], [0.4]], [[0.5]]]
    install_fake_client(monkeypatch, responses, calls)
    embedder = ZhipuEmbedder("key", dimensions=1024, batch_size=2)
    progress = []

    vectors = embedder.embed_documents(
        ["a", "b", "c", "d", "e"], progress=lambda done, total: progress.append((done, total))
    )

    assert len(vectors) == 5
    assert len(calls) == 3
    assert calls[0]["input"] == ["a", "b"]
    assert calls[0]["dimensions"] == 1024
    assert progress == [(2, 5), (4, 5), (5, 5)]

    responses.append([[0.9, 1.0]])
    assert embedder.embed_query("查询") == [0.9, 1.0]
    assert calls[-1]["input"] == ["查询"]


def test_dimension_fallback(monkeypatch):
    calls = []
    install_fake_client(
        monkeypatch,
        [Exception("dimension 1024 not supported"), [[0.1, 0.2]]],
        calls,
    )
    embedder = ZhipuEmbedder("key", dimensions=1024)

    assert embedder.embed_query("x") == [0.1, 0.2]
    assert embedder.dimensions is None
    assert calls[0]["dimensions"] == 1024
    assert "dimensions" not in calls[1]


def test_auth_error_and_persistent_failure(monkeypatch):
    calls = []
    install_fake_client(monkeypatch, [AuthError("unauthorized")], calls)
    embedder = ZhipuEmbedder("key")
    with pytest.raises(EmbeddingError, match="鉴权失败"):
        embedder.embed_query("x")
    assert len(calls) == 1

    calls = []
    install_fake_client(monkeypatch, [Exception("boom") for _ in range(4)], calls)
    embedder = ZhipuEmbedder("key")
    with pytest.raises(EmbeddingError, match="调用失败"):
        embedder.embed_query("x")
    assert len(calls) == 4


def test_prepare_strips_and_truncates():
    assert ZhipuEmbedder._prepare("  abc  ") == "abc"
    assert len(ZhipuEmbedder._prepare("  " + "x" * 7000)) == 6000
