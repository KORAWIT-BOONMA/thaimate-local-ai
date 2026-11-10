"""Gemini Developer API adapter for ThaiMate (Interactions API).

The API key is read from GEMINI_API_KEY in backend/.env or process env.
ThaiMate stores its own conversation history in SQLite, so requests are
stateless (store=False) and send the recent messages as interaction steps.
"""
from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from google import genai

BACKEND_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_DIR / ".env", override=False)

GEMINI_MODEL = (
    os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest").strip()
    or "gemini-flash-lite-latest"
)
logger = logging.getLogger(__name__)


class GeminiConfigurationError(Exception):
    """Gemini API is not configured."""


class GeminiAPIError(Exception):
    """Gemini API request failed."""


def is_gemini_configured() -> bool:
    return bool(os.getenv("GEMINI_API_KEY", "").strip())


def ensure_gemini_configured() -> None:
    if not is_gemini_configured():
        raise GeminiConfigurationError(
            "ยังไม่ได้ตั้งค่า GEMINI_API_KEY ในไฟล์ backend/.env"
        )


@lru_cache(maxsize=1)
def _client() -> genai.Client:
    ensure_gemini_configured()
    return genai.Client(api_key=os.environ["GEMINI_API_KEY"].strip())


def _prepare_messages(messages: list[dict]) -> tuple[str | None, list[dict]]:
    """Convert ThaiMate role/content messages to Interactions API steps."""
    system_parts: list[str] = []
    steps: list[dict] = []

    for message in messages:
        role = str(message.get("role", "user")).strip().lower()
        text = str(message.get("content", "") or "")
        if not text.strip():
            continue

        if role == "system":
            system_parts.append(text)
            continue

        if role == "assistant":
            step_type = "model_output"
        elif role == "user":
            step_type = "user_input"
        else:
            # Ignore unsupported roles rather than misrepresenting their meaning.
            continue

        steps.append(
            {
                "type": step_type,
                "content": [{"type": "text", "text": text}],
            }
        )

    if not steps:
        steps.append(
            {
                "type": "user_input",
                "content": [{"type": "text", "text": "สวัสดี"}],
            }
        )

    system_instruction = "\n\n".join(system_parts).strip() or None
    return system_instruction, steps


def _generation_config(max_output_tokens: int) -> dict:
    return {"max_output_tokens": max(128, int(max_output_tokens))}


def _get_output_text(interaction) -> str:
    """Read the convenience output_text field, with a steps fallback."""
    answer = getattr(interaction, "output_text", None)
    if isinstance(answer, str) and answer.strip():
        return answer.strip()

    pieces: list[str] = []
    for step in getattr(interaction, "steps", None) or []:
        if getattr(step, "type", None) != "model_output":
            continue
        for content in getattr(step, "content", None) or []:
            if getattr(content, "type", None) == "text":
                value = getattr(content, "text", None)
                if isinstance(value, str) and value:
                    pieces.append(value)
    return "".join(pieces).strip()


async def generate_text(
    messages: list[dict],
    *,
    max_output_tokens: int = 4096,
) -> str:
    """Run a non-streaming Gemini Interactions API request."""
    ensure_gemini_configured()
    system_instruction, steps = _prepare_messages(messages)

    try:
        logger.info("Gemini Interactions request: model=%s stream=false", GEMINI_MODEL)
        interaction = await _client().aio.interactions.create(
            model=GEMINI_MODEL,
            input=steps,
            system_instruction=system_instruction,
            generation_config=_generation_config(max_output_tokens),
            store=False,
        )
        answer = _get_output_text(interaction)
        if not answer:
            raise GeminiAPIError("Gemini ส่งคำตอบว่างกลับมา")
        return answer
    except GeminiAPIError:
        raise
    except Exception as exc:
        logger.exception("Gemini Interactions request failed")
        raise GeminiAPIError(_friendly_error(exc)) from exc


async def generate_stream(
    messages: list[dict],
    *,
    max_output_tokens: int = 4096,
) -> AsyncIterator[str]:
    """Stream text deltas from the Gemini Interactions API."""
    ensure_gemini_configured()
    system_instruction, steps = _prepare_messages(messages)
    emitted_text = False

    try:
        logger.info("Gemini Interactions request: model=%s stream=true", GEMINI_MODEL)
        stream = await _client().aio.interactions.create(
            model=GEMINI_MODEL,
            input=steps,
            system_instruction=system_instruction,
            generation_config=_generation_config(max_output_tokens),
            store=False,
            stream=True,
        )

        async for event in stream:
            if getattr(event, "event_type", None) != "step.delta":
                continue

            delta = getattr(event, "delta", None)
            if getattr(delta, "type", None) != "text":
                continue

            text = getattr(delta, "text", None)
            if isinstance(text, str) and text:
                emitted_text = True
                yield text

        if not emitted_text:
            raise GeminiAPIError("Gemini จบคำขอแล้ว แต่ไม่ได้ส่งข้อความกลับมา")

    except GeminiAPIError:
        raise
    except Exception as exc:
        logger.exception("Gemini Interactions streaming request failed")
        raise GeminiAPIError(_friendly_error(exc)) from exc


def _summarize_pdf_sync(
    pdf_path: str,
    *,
    system_instruction: str,
    prompt: str,
    max_output_tokens: int,
) -> str:
    """Upload a PDF and summarize it through the Interactions API."""
    client = _client()
    uploaded = None

    try:
        uploaded = client.files.upload(file=pdf_path)
        file_uri = getattr(uploaded, "uri", None)
        if not file_uri:
            raise GeminiAPIError("Gemini Files API ไม่ได้ส่ง URI ของไฟล์กลับมา")

        interaction = client.interactions.create(
            model=GEMINI_MODEL,
            input=[
                {
                    "type": "document",
                    "uri": file_uri,
                    "mime_type": getattr(uploaded, "mime_type", None)
                    or "application/pdf",
                },
                {"type": "text", "text": prompt},
            ],
            system_instruction=system_instruction or None,
            generation_config=_generation_config(max_output_tokens),
            store=False,
        )

        answer = _get_output_text(interaction)
        if not answer:
            raise GeminiAPIError("Gemini อ่าน PDF แล้วไม่ได้ส่งบทสรุปกลับมา")
        return answer

    except GeminiAPIError:
        raise
    except Exception as exc:
        logger.exception("Gemini PDF Interactions request failed")
        raise GeminiAPIError(_friendly_error(exc)) from exc
    finally:
        # Remove the temporary uploaded copy after the interaction completes.
        if uploaded is not None and getattr(uploaded, "name", None):
            try:
                client.files.delete(name=uploaded.name)
            except Exception:
                logger.warning(
                    "Could not delete temporary Gemini file: %s",
                    getattr(uploaded, "name", "unknown"),
                    exc_info=True,
                )


async def summarize_pdf_file(
    pdf_path: str | Path,
    *,
    system_instruction: str,
    prompt: str,
    max_output_tokens: int = 12000,
) -> str:
    """Summarize a local PDF with Gemini, preserving image/diagram input."""
    ensure_gemini_configured()
    path = Path(pdf_path).resolve()

    if not path.is_file() or path.suffix.lower() != ".pdf":
        raise GeminiAPIError("ไม่พบไฟล์ PDF ที่ต้องการส่งให้ Gemini")
    if path.stat().st_size > 50 * 1024 * 1024:
        raise GeminiAPIError("PDF มีขนาดเกินขีดจำกัด 50 MB ของ ThaiMate Gemini adapter")

    return await asyncio.to_thread(
        _summarize_pdf_sync,
        str(path),
        system_instruction=system_instruction,
        prompt=prompt,
        max_output_tokens=max_output_tokens,
    )


def _friendly_error(exc: Exception) -> str:
    raw = str(exc).strip()
    lowered = raw.lower()

    if "429" in raw or "resource_exhausted" in lowered or "quota" in lowered:
        return (
            "Gemini ใช้โควตาหรืออัตราการเรียก API ถึงขีดจำกัดแล้ว "
            "กรุณาตรวจสอบโควตาใน Google AI Studio"
        )
    if "503" in raw or "unavailable" in lowered or "high demand" in lowered:
        return (
            "Gemini กำลังมีผู้ใช้งานหนาแน่นหรือให้บริการชั่วคราวไม่ได้ "
            "กรุณาลองใหม่ภายหลัง หรือเลือก Qwen ในระหว่างนี้"
        )
    if "403" in raw or "permission_denied" in lowered or "api key" in lowered:
        return "Gemini ปฏิเสธคำขอ กรุณาตรวจสอบ GEMINI_API_KEY และสิทธิ์การใช้งานโมเดล"
    if "404" in raw or "not found" in lowered:
        return f"ไม่พบโมเดลหรือไฟล์ที่เรียกใช้ กรุณาตรวจสอบ GEMINI_MODEL ({GEMINI_MODEL}) และสิทธิ์ของ API Key"

    if len(raw) > 500:
        raw = raw[:500] + "..."
    return f"Gemini API error: {raw or type(exc).__name__}"
