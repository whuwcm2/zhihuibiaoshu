from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import redis


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class RedisJobRegistry:
    """保存任务元数据（文件名/创建时间），任务状态仍以 Celery 结果后端为准。"""

    def __init__(
        self,
        redis_url: str,
        prefix: str = "zhibiao:job:",
        ttl: int = 86400,
    ) -> None:
        self.client = redis.Redis.from_url(redis_url, decode_responses=True)
        self.prefix = prefix
        self.ttl = ttl

    def _key(self, job_id: str) -> str:
        return f"{self.prefix}{job_id}"

    def create(self, job_id: str, filename: str, **extra: Any) -> dict[str, Any]:
        payload = {
            "job_id": job_id,
            "filename": filename,
            "created_at": now_iso(),
            **extra,
        }
        self.client.set(
            self._key(job_id),
            json.dumps(payload, ensure_ascii=False),
            ex=self.ttl,
        )
        return payload

    def get(self, job_id: str) -> dict[str, Any] | None:
        raw = self.client.get(self._key(job_id))
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def ping(self) -> bool:
        return bool(self.client.ping())


class InMemoryJobRegistry:
    """测试/降级用内存实现。"""

    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}

    def create(self, job_id: str, filename: str, **extra: Any) -> dict[str, Any]:
        payload = {
            "job_id": job_id,
            "filename": filename,
            "created_at": now_iso(),
            **extra,
        }
        self._jobs[job_id] = payload
        return payload

    def get(self, job_id: str) -> dict[str, Any] | None:
        return self._jobs.get(job_id)

    def ping(self) -> bool:
        return True

    def clear(self) -> None:
        self._jobs.clear()
