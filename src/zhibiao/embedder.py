from __future__ import annotations

import time
from collections.abc import Callable

from zai import ZhipuAiClient

MAX_INPUT_CHARS = 6000


class EmbeddingError(RuntimeError):
    pass


class ZhipuEmbedder:
    """智谱 embedding-3 封装：批量、重试、维度自动降级。"""

    def __init__(
        self,
        api_key: str,
        model: str = "embedding-3",
        dimensions: int | None = None,
        batch_size: int = 32,
    ) -> None:
        if not api_key:
            raise EmbeddingError("ZHIPU_API_KEY 未配置")
        self.client = ZhipuAiClient(api_key=api_key, timeout=60, max_retries=0)
        self.model = model
        self.dimensions = dimensions
        self.batch_size = max(1, batch_size)

    def embed_documents(
        self,
        texts: list[str],
        progress: Callable[[int, int], None] | None = None,
    ) -> list[list[float]]:
        vectors: list[list[float]] = []
        total = len(texts)
        for start in range(0, total, self.batch_size):
            batch = [self._prepare(text) for text in texts[start:start + self.batch_size]]
            vectors.extend(self._embed_batch(batch))
            if progress:
                progress(min(start + len(batch), total), total)
        return vectors

    def embed_query(self, query: str) -> list[float]:
        return self._embed_batch([self._prepare(query)])[0]

    @staticmethod
    def _prepare(text: str) -> str:
        cleaned = text.strip()
        return cleaned[:MAX_INPUT_CHARS] if len(cleaned) > MAX_INPUT_CHARS else cleaned

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        last_error: Exception | None = None
        for attempt in range(4):
            kwargs: dict = {"model": self.model, "input": texts}
            if self.dimensions is not None:
                kwargs["dimensions"] = self.dimensions
            try:
                response = self.client.embeddings.create(**kwargs)
                items = sorted(response.data, key=lambda item: getattr(item, "index", 0))
                vectors = [list(map(float, item.embedding)) for item in items]
                if len(vectors) != len(texts):
                    raise EmbeddingError(
                        f"embedding 返回数量不匹配: {len(vectors)} != {len(texts)}"
                    )
                return vectors
            except Exception as exc:  # noqa: BLE001 - SDK 异常类型较杂
                message = str(exc).lower()
                if self.dimensions is not None and "dimension" in message:
                    print(
                        f"[warn] embedding-3 不支持 dimensions={self.dimensions}，"
                        "改用模型默认维度",
                        flush=True,
                    )
                    self.dimensions = None
                    continue
                status = getattr(exc, "status_code", None)
                if status in (401, 403):
                    raise EmbeddingError(f"智谱 API 鉴权失败: {exc}") from exc
                last_error = exc
                if attempt < 3:
                    time.sleep(2 ** attempt)

        raise EmbeddingError(f"智谱 embedding 调用失败: {last_error}")
