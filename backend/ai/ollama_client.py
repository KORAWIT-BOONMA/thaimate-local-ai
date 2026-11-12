import json
import logging
from collections.abc import AsyncIterator

import httpx


# ==========================================
# Ollama Configuration
# ==========================================

MODEL_NAME = "qwen3.5:4b"
OLLAMA_URL = "http://localhost:11434"

# Normal chat keeps the existing timeout.
TIMEOUT = httpx.Timeout(
    180.0,
    connect=10.0,
)

# Multi-pass document summaries may need longer per request on CPU inference.
# This is an HTTP read/inactivity timeout, not a guaranteed total-job deadline.
DOCUMENT_SUMMARY_TIMEOUT = httpx.Timeout(
    600.0,
    connect=10.0,
)

# Ryzen 5 5500GT / RAM 16GB / CPU inference:
# 4096 gives the prompt room beyond the previous 4096-token limit
# without jumping straight to a much larger context window.
NUM_CTX = 4096

# Keep enough room for tables, explanations, and source citations.
# Ollama may stop earlier when the model finishes its answer.
NUM_PREDICT = 1200

# Keep current memory behavior unchanged.
KEEP_ALIVE = 0

# Qwen3.5 non-thinking generation settings.
TEMPERATURE = 0.7
TOP_P = 0.8
TOP_K = 20
PRESENCE_PENALTY = 1.5

logger = logging.getLogger(__name__)


# ==========================================
# Custom Errors
# ==========================================

class OllamaConnectionError(Exception):
    pass


class OllamaTimeoutError(Exception):
    pass


class OllamaResponseError(Exception):
    pass


# ==========================================
# Token Statistics
# ==========================================

def log_token_statistics(
    data: dict,
    *,
    max_output_tokens: int = NUM_PREDICT,
) -> None:
    """Log token usage and generation performance."""

    prompt_tokens = data.get("prompt_eval_count", 0)
    output_tokens = data.get("eval_count", 0)

    prompt_duration = data.get("prompt_eval_duration", 0)
    eval_duration = data.get("eval_duration", 0)

    done_reason = data.get("done_reason", "unknown")

    total_tokens = prompt_tokens + output_tokens

    generation_speed = (
        output_tokens / (eval_duration / 1_000_000_000)
        if eval_duration > 0
        else 0
    )

    logger.info(
        "\n"
        "========== THAIMATE TOKEN STATISTICS ==========\n"
        "Model: %s\n"
        "Context Window: %s\n"
        "Maximum Output Tokens: %s\n"
        "Input Tokens: %s\n"
        "Output Tokens: %s\n"
        "Total Tokens: %s\n"
        "Prompt Duration: %.2f seconds\n"
        "Generation Duration: %.2f seconds\n"
        "Generation Speed: %.2f tokens/sec\n"
        "Done Reason: %s\n"
        "================================================",
        MODEL_NAME,
        NUM_CTX,
        max_output_tokens,
        prompt_tokens,
        output_tokens,
        total_tokens,
        prompt_duration / 1_000_000_000,
        eval_duration / 1_000_000_000,
        generation_speed,
        done_reason,
    )


# ==========================================
# Payload Builder
# ==========================================

def build_payload(
    messages: list[dict],
    stream: bool = False,
    *,
    num_predict: int | None = None,
) -> dict:
    """Build one Ollama payload, with optional per-request output budget."""

    effective_num_predict = (
        NUM_PREDICT if num_predict is None else max(1, int(num_predict))
    )

    ollama_messages = []
    for message in messages:
        normalized = dict(message)
        attachments = normalized.get("images")
        if isinstance(attachments, list):
            image_data = [
                item.get("data")
                for item in attachments
                if isinstance(item, dict) and isinstance(item.get("data"), str)
            ]
            if image_data:
                normalized["images"] = image_data
            else:
                normalized.pop("images", None)
        ollama_messages.append(normalized)

    return {
        "model": MODEL_NAME,
        "messages": ollama_messages,
        "stream": stream,
        "think": False,
        "keep_alive": KEEP_ALIVE,
        "options": {
            "num_ctx": NUM_CTX,
            "num_predict": effective_num_predict,
            "temperature": TEMPERATURE,
            "top_p": TOP_P,
            "top_k": TOP_K,
            "presence_penalty": PRESENCE_PENALTY,
        },
    }


# ==========================================
# Error Handling
# ==========================================

def handle_http_error(exc: Exception) -> Exception:

    if isinstance(exc, httpx.ConnectError):
        return OllamaConnectionError(
            "เชื่อมต่อ Ollama ไม่ได้ กรุณาตรวจสอบว่า Ollama กำลังทำงาน"
        )

    if isinstance(exc, httpx.TimeoutException):
        return OllamaTimeoutError(
            "Ollama ใช้เวลาประมวลผลนานเกินกำหนด"
        )

    return OllamaResponseError(
        f"เกิดข้อผิดพลาดในการเรียก Ollama: {exc}"
    )


# ==========================================
# Normal Chat Completion
# ==========================================

async def chat_completion(
    messages: list[dict],
    *,
    timeout: httpx.Timeout | None = None,
    num_predict: int | None = None,
) -> str:
    """Run a non-streaming request with optional timeout and output overrides."""

    effective_num_predict = (
        NUM_PREDICT if num_predict is None else max(1, int(num_predict))
    )
    payload = build_payload(
        messages,
        stream=False,
        num_predict=effective_num_predict,
    )

    try:
        async with httpx.AsyncClient(
            timeout=timeout or TIMEOUT
        ) as client:

            response = await client.post(
                f"{OLLAMA_URL}/api/chat",
                json=payload,
            )

            if not response.is_success:
                raise OllamaResponseError(
                    f"Ollama ตอบ error: {response.text}"
                )

            try:
                data = response.json()
            except ValueError as exc:
                raise OllamaResponseError(
                    "Ollama ส่งข้อมูล JSON ไม่ถูกต้อง"
                ) from exc

            message = data.get("message", {})

            if not isinstance(message, dict):
                raise OllamaResponseError(
                    "รูปแบบคำตอบจาก Ollama ไม่ถูกต้อง"
                )

            content = message.get("content", "")

            if not isinstance(content, str):
                raise OllamaResponseError(
                    "เนื้อหาคำตอบจาก Ollama ไม่ถูกต้อง"
                )

            log_token_statistics(
                data,
                max_output_tokens=effective_num_predict,
            )

            return content

    except httpx.TimeoutException as exc:
        logger.error(
            "Ollama chat completion timed out: error_type=%s | detail=%s",
            type(exc).__name__,
            str(exc) or "no additional detail",
        )
        raise handle_http_error(exc) from exc

    except httpx.HTTPError as exc:
        logger.exception("Ollama chat completion HTTP error")
        raise handle_http_error(exc) from exc


# ==========================================
# Streaming Chat
# ==========================================

async def chat_stream(
    messages: list[dict],
) -> AsyncIterator[str]:

    payload = build_payload(
        messages,
        stream=True,
    )

    final_statistics = None

    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT
        ) as client:

            async with client.stream(
                "POST",
                f"{OLLAMA_URL}/api/chat",
                json=payload,
            ) as response:

                if not response.is_success:
                    body = await response.aread()

                    raise OllamaResponseError(
                        "Ollama ตอบ error: "
                        + body.decode(
                            "utf-8",
                            errors="replace",
                        )
                    )

                async for line in response.aiter_lines():

                    if not line:
                        continue

                    try:
                        chunk = json.loads(line)

                    except json.JSONDecodeError:
                        continue

                    if chunk.get("error"):
                        raise OllamaResponseError(
                            f"Ollama error: {chunk['error']}"
                        )

                    message = chunk.get("message", {})

                    if isinstance(message, dict):
                        content = message.get("content", "")

                        if content:
                            yield content

                    if chunk.get("done", False):
                        final_statistics = chunk

                        log_token_statistics(chunk)

                        break

                if final_statistics is None:
                    logger.warning(
                        "Ollama stream ended without done=true"
                    )

    except httpx.HTTPError as exc:
        raise handle_http_error(exc) from exc
