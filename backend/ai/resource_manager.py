import asyncio
import logging
import time
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

# Ollama is shared by Qwen and BGE-M3. Only one model request runs at a time.
_request_lock = asyncio.Lock()
_queued_requests = 0
_active_task = None
_active_since = None


@asynccontextmanager
async def ollama_request(task_name: str):
    """Serialize Ollama calls so local models do not compete for RAM/VRAM."""
    global _queued_requests, _active_task, _active_since

    task_name = str(task_name or "ollama_request")
    queued_at = time.monotonic()
    _queued_requests += 1
    queue_position = _queued_requests

    logger.info(
        "Ollama request queued: task=%s | queue_position=%s | active=%s",
        task_name,
        queue_position,
        _active_task,
    )

    acquired = False
    try:
        await _request_lock.acquire()
        acquired = True
        _queued_requests = max(0, _queued_requests - 1)
        waited_seconds = time.monotonic() - queued_at
        _active_task = task_name
        _active_since = time.time()

        logger.info(
            "Ollama request started: task=%s | waited=%.2fs | queued=%s",
            task_name,
            waited_seconds,
            _queued_requests,
        )

        started_at = time.monotonic()
        try:
            yield
        finally:
            elapsed_seconds = time.monotonic() - started_at
            logger.info(
                "Ollama request finished: task=%s | duration=%.2fs",
                task_name,
                elapsed_seconds,
            )
    finally:
        if acquired:
            _active_task = None
            _active_since = None
            _request_lock.release()
        else:
            _queued_requests = max(0, _queued_requests - 1)


def get_resource_snapshot() -> dict:
    """Return the in-process Ollama queue state without exposing secrets."""
    return {
        "max_concurrent_requests": 1,
        "active_task": _active_task,
        "active_since": _active_since,
        "queued_requests": _queued_requests,
        "is_busy": _active_task is not None,
    }
