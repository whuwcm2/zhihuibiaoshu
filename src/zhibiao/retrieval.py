from __future__ import annotations

import math
import re
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Literal

from langsmith import traceable

from .config import Settings
from .embedder import ZhipuEmbedder
from .metadata import normalize_metadata
from .store import ChunkStore

# 智谱 embedding 客户端首次请求会有约 40s 冷启动；进程内复用同一个 client。
@lru_cache(maxsize=4)
def _cached_embedder(
    api_key: str, model: str, dimensions: int | None
) -> ZhipuEmbedder:
    return ZhipuEmbedder(
        api_key=api_key,
        model=model,
        dimensions=dimensions,
    )


_EMBED_LOCK = threading.Lock()


def _embed_query(
    embedder: ZhipuEmbedder, query: str, dimensions: int | None = None
) -> list[float]:
    """串行化 embedding 请求，避免并发触发多次冷启动。"""
    with _EMBED_LOCK:
        try:
            return embedder.embed_query(query, dimensions=dimensions)
        except TypeError:
            return embedder.embed_query(query)


def warm_up_embedder(settings: Settings) -> None:
    """后台预热 embedding client，避免首次搜索等待冷启动。"""
    embedder = _cached_embedder(
        settings.zhipu_api_key,
        settings.embedding_model,
        settings.embedding_dimensions,
    )
    warm_dimensions = (
        768 if settings.embedding_dimensions == 1024
        else settings.embedding_dimensions
    )
    _embed_query(embedder, "投标文件检索预热", dimensions=warm_dimensions)
    print("[search] embedding 预热完成", flush=True)

Intent = Literal["formula", "section_writing", "qualification", "general"]

INTENT_KEYWORDS: dict[Intent, tuple[str, ...]] = {
    "qualification": (
        "资格审查",
        "资格要求",
        "资格材料",
        "投标人资格",
        "资质",
        "营业执照",
        "安全生产许可证",
        "业绩",
        "财务",
        "信用",
        "证书",
        "qualification",
        "license",
    ),
    "formula": (
        "公式",
        "计算",
        "费率",
        "定额",
        "工程量",
        "计价",
        "折算",
        "评分计算",
        "formula",
        "calculation",
    ),
    "section_writing": (
        "怎么写",
        "如何写",
        "写法",
        "编制",
        "章节",
        "施工组织设计",
        "技术标",
        "商务标",
        "方案",
        "措施",
        "格式",
        "目录",
        "section",
        "writing",
    ),
}
_INTENT_PRIORITY: tuple[Intent, ...] = ("qualification", "formula", "section_writing")

_ASCII_RE = re.compile(r"[a-z0-9]+")
_CJK_RE = re.compile(r"[一-鿿]+")


def detect_intent(query: str) -> Intent:
    lowered = query.lower()
    scores = {
        intent: sum(1 for keyword in keywords if keyword in lowered)
        for intent, keywords in INTENT_KEYWORDS.items()
    }
    best = max(scores.values(), default=0)
    if best == 0:
        return "general"
    for intent in _INTENT_PRIORITY:
        if scores[intent] == best:
            return intent
    return "general"


def tokenize(text: str) -> list[str]:
    """中文按字符 bigram、英文/数字按单词切分，避免额外分词依赖。"""
    lowered = text.lower()
    tokens = _ASCII_RE.findall(lowered)
    for sequence in _CJK_RE.findall(lowered):
        if len(sequence) == 1:
            tokens.append(sequence)
        else:
            tokens.extend(sequence[index:index + 2] for index in range(len(sequence) - 1))
    return tokens


class BM25:
    def __init__(
        self, corpus: list[list[str]], k1: float = 1.5, b: float = 0.75
    ) -> None:
        self.corpus = corpus
        self.k1 = k1
        self.b = b
        self.doc_len = [len(document) for document in corpus]
        self.avgdl = (
            sum(self.doc_len) / len(self.doc_len) if self.doc_len else 0.0
        )
        self.term_freqs = [Counter(document) for document in corpus]
        document_freq: Counter[str] = Counter()
        for frequencies in self.term_freqs:
            document_freq.update(frequencies.keys())
        total = len(corpus)
        self.idf = {
            term: math.log(1 + (total - frequency + 0.5) / (frequency + 0.5))
            for term, frequency in document_freq.items()
        }

    def scores(self, query_tokens: list[str]) -> list[float]:
        scores = [0.0] * len(self.corpus)
        if not self.corpus or self.avgdl <= 0:
            return scores
        for term in set(query_tokens):
            idf = self.idf.get(term)
            if idf is None:
                continue
            for index, frequencies in enumerate(self.term_freqs):
                frequency = frequencies.get(term, 0)
                if not frequency:
                    continue
                denominator = frequency + self.k1 * (
                    1 - self.b + self.b * self.doc_len[index] / self.avgdl
                )
                scores[index] += idf * frequency * (self.k1 + 1) / denominator
        return scores


def _rank_indices(
    scores: list[float], limit: int, positive_only: bool = True
) -> list[int]:
    if limit <= 0:
        return []
    candidates = [
        index
        for index, score in enumerate(scores)
        if score > 0 or not positive_only
    ]
    return sorted(candidates, key=lambda index: scores[index], reverse=True)[:limit]


@dataclass
class _Candidate:
    chunk_id: str
    text: str
    metadata: dict[str, Any]
    fused: float = 0.0
    bm25: float = 0.0
    vector: float | None = None
    forced: bool = False
    reasons: set[str] = field(default_factory=set)


class HybridRetriever:
    RRF_K = 60

    def __init__(
        self,
        settings: Settings,
        store: ChunkStore | None = None,
        embedder: ZhipuEmbedder | None = None,
    ) -> None:
        self.settings = settings
        self.store = store or ChunkStore(
            settings.chroma_dir, settings.chroma_collection
        )
        self.embedder = embedder
        self.embedder_error: str | None = None
        if self.embedder is None:
            try:
                self.embedder = _cached_embedder(
                    settings.zhipu_api_key,
                    settings.embedding_model,
                    settings.embedding_dimensions,
                )
            except Exception as exc:  # noqa: BLE001 - 无 Key 时退化为 BM25
                self.embedder_error = str(exc)

    @traceable(name="search.hybrid", run_type="chain")
    def search(
        self,
        query: str,
        n_results: int = 5,
        intent: Intent | None = None,
    ) -> dict[str, Any]:
        query = query.strip()
        if not query:
            raise ValueError("查询不能为空")
        started = time.perf_counter()
        intent = intent or detect_intent(query)
        if intent not in INTENT_KEYWORDS and intent != "general":
            intent = "general"

        try:
            data = self.store.all_chunks(include_embeddings=True)
        except TypeError:
            data = self.store.all_chunks()
        raw_ids = list(data.get("ids") or [])
        raw_documents = list(data.get("documents") or [])
        raw_metadatas = list(data.get("metadatas") or [])
        stored_embeddings = data.get("embeddings")
        if not raw_ids:
            raise RuntimeError("向量库为空，请先执行 ingest")

        normalised: list[tuple[str, str, dict[str, Any]]] = []
        for chunk_id, text, metadata in zip(raw_ids, raw_documents, raw_metadatas):
            document = text or ""
            normalised.append(
                (chunk_id, document, normalize_metadata(chunk_id, document, metadata))
            )
        ids = [item[0] for item in normalised]
        texts = [item[1] for item in normalised]
        metadatas = [item[2] for item in normalised]

        query_tokens = tokenize(query)
        all_tokens = [
            tokenize(f"{metadata.get('heading') or ''}\n{text}")
            for text, metadata in zip(texts, metadatas)
        ]
        all_scores = BM25(all_tokens).scores(query_tokens)

        table_positions = [
            index
            for index, metadata in enumerate(metadatas)
            if metadata.get("type") == "table"
        ]
        table_scores = BM25(
            [all_tokens[index] for index in table_positions]
        ).scores(query_tokens)
        table_top = [
            table_positions[index]
            for index in _rank_indices(table_scores, max(n_results, 6))
        ]

        heading_tokens = [
            tokenize(str(metadata.get("heading") or ""))
            for metadata in metadatas
        ]
        heading_scores = BM25(heading_tokens).scores(query_tokens)
        heading_top = _rank_indices(heading_scores, max(n_results, 6))

        qualification_positions = [
            index
            for index, metadata in enumerate(metadatas)
            if metadata.get("qualification")
        ]
        qualification_scores = BM25(
            [all_tokens[index] for index in qualification_positions]
        ).scores(query_tokens)
        qualification_top = [
            qualification_positions[index]
            for index in _rank_indices(
                qualification_scores,
                max(n_results * 2, 8),
                positive_only=False,
            )
        ]

        weights = {
            "bm25": 1.0,
            "table": 2.2 if intent == "formula" else 1.4,
            "heading": 2.0 if intent == "section_writing" else 1.1,
            "qualification": 2.5 if intent == "qualification" else 0.0,
            "vector": 1.0,
        }

        candidates: dict[str, _Candidate] = {}
        positions = {chunk_id: index for index, chunk_id in enumerate(ids)}

        def candidate_for(index: int) -> _Candidate:
            chunk_id = ids[index]
            candidate = candidates.get(chunk_id)
            if candidate is None:
                candidate = _Candidate(chunk_id, texts[index], metadatas[index])
                candidates[chunk_id] = candidate
            return candidate

        def add_ranked(
            indices: list[int],
            weight: float,
            reason: str,
            *,
            forced: bool = False,
        ) -> None:
            if weight <= 0:
                return
            for rank, index in enumerate(indices, start=1):
                candidate = candidate_for(index)
                candidate.fused += weight / (self.RRF_K + rank)
                candidate.bm25 = max(candidate.bm25, all_scores[index])
                candidate.reasons.add(reason)
                if forced:
                    candidate.forced = True

        add_ranked(
            _rank_indices(all_scores, max(n_results * 3, 10)),
            weights["bm25"],
            "bm25",
        )
        add_ranked(table_top, weights["table"], "bm25_table")
        add_ranked(heading_top, weights["heading"], "bm25_heading")

        forced_ids: list[str] = []
        if intent == "qualification" and qualification_top:
            forced_limit = min(
                len(qualification_top), max(1, n_results // 2)
            )
            forced_ids = [
                ids[index] for index in qualification_top[:forced_limit]
            ]
            add_ranked(
                qualification_top,
                weights["qualification"],
                "qualification",
                forced=True,
            )

        vector_error: str | None = self.embedder_error
        vector_ids: list[str] = []
        vector_weight = weights["vector"]
        try:
            if self.embedder is None:
                raise RuntimeError(self.embedder_error or "embedding 不可用")

            dense_scan = (
                stored_embeddings is not None
                and len(stored_embeddings) > 0
                and len(stored_embeddings[0]) > 0
            )
            if dense_scan:
                stored_dim = len(stored_embeddings[0])
                # 智谱 embedding-3 在 dimensions=1024 时响应异常慢；
                # 768 维是 1024 维向量的前缀，可直接与已存向量前缀做余弦。
                query_dim = 768 if stored_dim == 1024 else stored_dim
                query_vector = _embed_query(
                    self.embedder, query, dimensions=query_dim
                )
                dims = min(len(query_vector), stored_dim)
                if dims <= 0:
                    raise RuntimeError("查询向量维度为空")
                query_slice = [
                    float(value) for value in query_vector[:dims]
                ]
                query_norm = math.sqrt(
                    sum(value * value for value in query_slice)
                )
                scored: list[tuple[int, float]] = []
                for index, vector in enumerate(stored_embeddings):
                    if len(vector) < dims:
                        continue
                    dot = sum(
                        query_slice[position] * float(vector[position])
                        for position in range(dims)
                    )
                    vector_norm = math.sqrt(
                        sum(
                            float(vector[position]) ** 2
                            for position in range(dims)
                        )
                    )
                    score = (
                        dot / (query_norm * vector_norm)
                        if query_norm and vector_norm
                        else 0.0
                    )
                    scored.append((index, max(0.0, score)))
                scored.sort(key=lambda item: item[1], reverse=True)
                for rank, (index, score) in enumerate(
                    scored[: max(n_results * 2, 8)], start=1
                ):
                    chunk_id = ids[index]
                    candidate = candidate_for(index)
                    candidate.fused += vector_weight / (self.RRF_K + rank)
                    candidate.vector = round(score, 6)
                    candidate.reasons.add("vector")
                    vector_ids.append(chunk_id)
            else:
                embedding = _embed_query(self.embedder, query)
                vector_result = self.store.query(
                    embedding, n_results=max(n_results * 2, 8)
                )
                vector_ids = list((vector_result.get("ids") or [[]])[0])
                vector_documents = list(
                    (vector_result.get("documents") or [[]])[0]
                )
                vector_metadatas = list(
                    (vector_result.get("metadatas") or [[]])[0]
                )
                vector_distances = list(
                    (vector_result.get("distances") or [[]])[0]
                )
                for rank, (chunk_id, document, metadata, distance) in enumerate(
                    zip(
                        vector_ids,
                        vector_documents,
                        vector_metadatas,
                        vector_distances,
                    ),
                    start=1,
                ):
                    if chunk_id not in candidates:
                        if chunk_id not in positions:
                            positions[chunk_id] = len(ids)
                            ids.append(chunk_id)
                            texts.append(document or "")
                            metadatas.append(
                                normalize_metadata(
                                    chunk_id, document or "", metadata
                                )
                            )
                            all_scores.append(0.0)
                        candidate = _Candidate(
                            chunk_id,
                            document or "",
                            normalize_metadata(chunk_id, document or "", metadata),
                        )
                        candidates[chunk_id] = candidate
                    candidate = candidates[chunk_id]
                    candidate.fused += vector_weight / (self.RRF_K + rank)
                    candidate.vector = max(0.0, 1.0 - float(distance))
                    candidate.reasons.add("vector")
        except Exception as exc:  # noqa: BLE001 - 向量不可用时保留关键词结果
            vector_error = str(exc)
            print(f"[search] 向量检索不可用，使用 BM25 结果：{exc}", flush=True)

        ordered_ids = forced_ids + [
            chunk_id
            for chunk_id in sorted(
                candidates,
                key=lambda item: candidates[item].fused,
                reverse=True,
            )
            if chunk_id not in forced_ids
        ]
        selected = ordered_ids[:n_results]
        max_fused = max(
            (candidates[chunk_id].fused for chunk_id in selected), default=0.0
        )
        max_bm25 = max(all_scores, default=0.0)

        results = []
        for chunk_id in selected:
            candidate = candidates[chunk_id]
            metadata = candidate.metadata
            tags = [
                tag
                for tag in str(metadata.get("tags") or "").split(",")
                if tag
            ]
            results.append(
                {
                    "id": chunk_id,
                    "doc_id": metadata.get("doc_id"),
                    "text": candidate.text,
                    "snippet": candidate.text[:300].replace("\n", " "),
                    "heading": str(metadata.get("heading") or ""),
                    "page_start": int(metadata.get("page_start") or 0),
                    "page_end": int(metadata.get("page_end") or 0),
                    "source": metadata.get("source"),
                    "type": str(metadata.get("type") or "text"),
                    "table_id": str(metadata.get("table_id") or ""),
                    "tags": tags,
                    "score": round(
                        candidate.fused / max_fused, 4
                    ) if max_fused else 0.0,
                    "keyword_score": round(
                        candidate.bm25 / max_bm25, 4
                    ) if max_bm25 else 0.0,
                    "vector_score": (
                        round(candidate.vector, 4)
                        if candidate.vector is not None
                        else None
                    ),
                    "forced": chunk_id in forced_ids,
                    "reasons": sorted(candidate.reasons),
                }
            )

        return {
            "query": query,
            "intent": intent,
            "strategy": {
                "keyword_candidates": len(_rank_indices(all_scores, len(ids))),
                "table_candidates": len(table_top),
                "heading_candidates": len(heading_top),
                "qualification_candidates": len(qualification_positions),
                "forced_qualification": len(forced_ids),
                "vector_candidates": len(vector_ids),
                "vector_error": vector_error,
                "weights": weights,
            },
            "candidate_count": len(normalised),
            "took_ms": int((time.perf_counter() - started) * 1000),
            "results": results,
        }
