from __future__ import annotations

from typing import Any, Protocol

from redis import Redis


class JobQueue(Protocol):
    def enqueue(self, job_id: str) -> None:
        """Wake workers for a durable PostgreSQL job id."""

    def dequeue(self, *, timeout_seconds: int = 1) -> str | None:
        """Return a job id delivered by the queue, if any."""


class RedisJobQueue:
    def __init__(self, redis_client: Redis, *, queue_name: str = "launch_os_v11:jobs") -> None:
        self._redis = redis_client
        self.queue_name = queue_name

    def enqueue(self, job_id: str) -> None:
        self._redis.rpush(self.queue_name, job_id)

    def dequeue(self, *, timeout_seconds: int = 1) -> str | None:
        item: Any = self._redis.blpop([self.queue_name], timeout=timeout_seconds)
        if item is None:
            return None
        raw_job_id = item[1]
        if isinstance(raw_job_id, bytes):
            return raw_job_id.decode("utf-8")
        return str(raw_job_id)


def create_redis_job_queue(redis_url: str) -> RedisJobQueue:
    client: Redis = Redis.from_url(redis_url, decode_responses=True)
    return RedisJobQueue(client)
