import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Literal

import db
import workspace

from ai.assistant import generate_reply, generate_stream

from ai.ollama_client import (
    MODEL_NAME,
    OllamaConnectionError,
    OllamaTimeoutError,
    OllamaResponseError,
)
from ai.gemini_client import (
    GEMINI_MODEL,
    GeminiAPIError,
    GeminiConfigurationError,
    ensure_gemini_configured,
    is_gemini_configured,
)

from ai.embeddings import EmbeddingError

from ai.knowledge import (
    index_workspace_file,
    search_knowledge,
    list_knowledge_sources,
    delete_document,
    init_knowledge_db,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)


# Logger Configuration
logger = logging.getLogger(__name__)

app = FastAPI(title="ThaiMate AI")


# ==========================================
# CORS Configuration
# ==========================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Conversation-Id"],
)


# ==========================================
# Startup
# ==========================================

@app.on_event("startup")
def startup():
    db.init_db()
    init_knowledge_db()


# ==========================================
# Request Models
# ==========================================

class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[Message]
    conversation_id: int | None = None
    knowledge_source: str | None = None
    model_provider: Literal["ollama", "gemini"] = "ollama"
    cloud_consent: bool = False


class WriteRequest(BaseModel):
    path: str
    content: str
    overwrite: bool = False


class RunRequest(BaseModel):
    path: str
    # Retained for frontend compatibility.
    # This value is NOT a security authorization mechanism.
    approved: bool = False


class KnowledgeIndexRequest(BaseModel):
    path: str


class KnowledgeSearchRequest(BaseModel):
    query: str
    top_k: int = 5
    source: str | None = None


class KnowledgeDeleteRequest(BaseModel):
    source: str


def require_cloud_consent(req: ChatRequest):
    """Require explicit consent before sending data to Gemini."""

    if req.model_provider == "gemini" and not req.cloud_consent:
        raise HTTPException(
            status_code=403,
            detail=(
                "ต้องได้รับความยินยอมก่อนส่งข้อมูลไปยัง Gemini Cloud "
                "ข้อมูลสนทนาและบริบทจากไฟล์ที่เกี่ยวข้องอาจถูกส่งออกไปประมวลผล"
            ),
        )

# ==========================================
# General API
# ==========================================

@app.get("/")
def root():
    return {
        "message": "ThaiMate ทำงานอยู่",
        "model": MODEL_NAME,
        "cloud_model": GEMINI_MODEL,
        "gemini_configured": is_gemini_configured(),
    }


@app.get("/models")
def models():
    """List available model providers without exposing API credentials."""
    return {
        "default": "ollama",
        "models": [
            {"id": "ollama", "name": MODEL_NAME, "label": "Qwen 3.5 4B · Local", "available": True},
            {"id": "gemini", "name": GEMINI_MODEL, "label": "Gemini · Cloud", "available": is_gemini_configured()},
        ],
    }


# ==========================================
# Conversation API
# ==========================================

@app.get("/conversations")
def conversations():
    return db.list_conversations()


@app.get("/conversations/{conversation_id}/messages")
def conversation_messages(conversation_id: int):
    return db.get_messages(conversation_id)


@app.delete("/conversations/{conversation_id}")
def conversation_delete(conversation_id: int):
    """Delete one conversation and all its messages."""
    if conversation_id <= 0:
        raise HTTPException(status_code=400, detail="รหัสบทสนทนาไม่ถูกต้อง")
    deleted = db.delete_conversation(conversation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="ไม่พบบทสนทนาที่ต้องการลบ")
    logger.info("Conversation deleted: id=%s", conversation_id)
    return {"success": True, "conversation_id": conversation_id}


@app.delete("/conversations")
def conversations_delete_all():
    """Delete all conversations; knowledge files and indexes are untouched."""
    deleted_count = db.delete_all_conversations()
    logger.info("All conversations deleted: count=%s", deleted_count)
    return {"success": True, "deleted_count": deleted_count}


# ==========================================
# Workspace API
# ==========================================

@app.get("/files")
def files():
    return workspace.list_files()


@app.get("/files/read")
def files_read(path: str):
    try:
        return {
            "path": path,
            "content": workspace.read_file(path),
        }
    except workspace.WorkspaceError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e),
        )


@app.post("/files/upload")
async def files_upload(file: UploadFile = File(...), overwrite: bool = False):
    """Upload a document into Workspace and index it for RAG."""
    filename = file.filename or ""
    content = await file.read(workspace.MAX_UPLOAD_BYTES + 1)
    await file.close()

    if len(content) > workspace.MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="ไฟล์มีขนาดเกิน 10 MB")

    # Keep a copy so a failed re-index can restore the previous file.
    relative_name = Path(filename.replace("\\", "/")).name
    relative_path = f"{workspace.UPLOAD_DIRECTORY}/{relative_name}"
    target = workspace.safe_path(relative_path)
    previous_content = None
    if target.is_file():
        if target.stat().st_size > workspace.MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=400, detail="ไฟล์เดิมมีขนาดเกินขีดจำกัดที่ระบบจัดการได้")
        previous_content = target.read_bytes()

    try:
        saved = workspace.save_uploaded_file(filename, content, overwrite=overwrite)
    except workspace.FileExistsConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except workspace.WorkspaceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        indexed = await index_workspace_file(saved["path"])
    except Exception as exc:
        # Restore the previous file (if any) so file contents and old index stay in sync.
        try:
            if previous_content is None:
                target.unlink(missing_ok=True)
                delete_document(saved["path"])
            else:
                workspace.save_uploaded_file(
                    relative_name, previous_content, overwrite=True
                )
        except Exception:
            logger.exception("Failed to roll back uploaded file: %s", saved["path"])
        logger.exception("Upload/index failed for %s", saved["path"])
        status_code = 400 if isinstance(
            exc, (workspace.WorkspaceError, ValueError, EmbeddingError)
        ) else 500
        raise HTTPException(
            status_code=status_code,
            detail=f"ไม่สามารถเพิ่มไฟล์เข้าคลังความรู้ได้ ระบบคืนไฟล์เดิมให้แล้ว: {exc}",
        ) from exc

    logger.info(
        "Document uploaded and indexed: source=%s chunks=%s bytes=%s",
        saved["path"], indexed["chunks"], saved["size"],
    )
    return {
        "success": True,
        "source": saved["path"],
        "filename": saved["filename"],
        "size": saved["size"],
        "chunks": indexed["chunks"],
        "indexed": True,
    }


@app.delete("/files")
def files_delete(path: str):
    """Delete an uploaded file and its RAG chunks."""
    try:
        target = workspace.safe_path(path)
    except workspace.WorkspaceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not target.is_file():
        raise HTTPException(status_code=404, detail="ไม่พบไฟล์")
    relative = target.relative_to(workspace.WORKSPACE)
    if not relative.parts or relative.parts[0] != workspace.UPLOAD_DIRECTORY:
        raise HTTPException(status_code=400, detail="ลบได้เฉพาะไฟล์ที่อัปโหลดเข้าระบบผ่าน ThaiMate")
    if target.stat().st_size > workspace.MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="ไฟล์นี้มีขนาดเกินขีดจำกัดที่ระบบจัดการได้")
    previous_content = target.read_bytes()

    try:
        workspace.delete_uploaded_file(path)
        deleted_chunks = delete_document(path)
    except workspace.WorkspaceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        # Best-effort recovery if the database operation fails after file deletion.
        try:
            workspace.save_uploaded_file(Path(path).name, previous_content, overwrite=False)
        except Exception:
            logger.exception("Failed to restore deleted upload: %s", path)
        logger.exception("Failed to remove knowledge chunks for %s", path)
        raise HTTPException(status_code=500, detail="ลบข้อมูลความรู้ไม่สำเร็จ") from exc

    return {
        "success": True,
        "path": path,
        "deleted_chunks": deleted_chunks,
    }


@app.post("/files/write")
def files_write(req: WriteRequest):
    try:
        return workspace.write_file(
            req.path,
            req.content,
            req.overwrite,
        )

    except workspace.FileExistsConflict as e:
        raise HTTPException(status_code=409, detail=str(e))

    except workspace.WorkspaceError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ==========================================
# Code Execution API
# ==========================================

@app.get("/run/preview")
def run_preview(path: str):
    """Preview a Python command without executing it."""

    try:
        return workspace.run_preview(path)

    except workspace.WorkspaceError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc


@app.post("/run")
def run(req: RunRequest):
    """Execute generated code only when a secure runner is available."""

    # Keep execution disabled until an isolated sandbox exists.
    if not workspace.RUN_EXECUTION_ENABLED:
        raise HTTPException(
            status_code=503,
            detail=(
                "ระบบรัน Python ถูกปิดไว้ชั่วคราวเพื่อความปลอดภัย "
                "ยังสามารถสร้าง บันทึก อ่าน และ Preview โค้ดได้"
            ),
        )

    # Retained as an additional UI confirmation check.
    # This boolean alone must never be treated as secure authorization.
    if not req.approved:
        raise HTTPException(
            status_code=403,
            detail="ต้องได้รับการอนุมัติก่อนรัน",
        )

    try:
        return workspace.run_file(req.path)

    except workspace.WorkspaceError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc


# ==========================================
# Local Knowledge API
# ==========================================

@app.post("/knowledge/index")
async def knowledge_index(req: KnowledgeIndexRequest):
    try:
        return await index_workspace_file(req.path)

    except workspace.WorkspaceError as e:
        raise HTTPException(status_code=400, detail=str(e))

    except (ValueError, EmbeddingError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/knowledge/sources")
def knowledge_sources():
    return list_knowledge_sources()


@app.post("/knowledge/search")
async def knowledge_search(req: KnowledgeSearchRequest):
    try:
        results = await search_knowledge(
            req.query,
            req.top_k,
            source=req.source,
        )

        return {
            "query": req.query,
            "results": results,
        }

    except workspace.WorkspaceError as e:
        raise HTTPException(status_code=400, detail=str(e))

    except (ValueError, EmbeddingError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/knowledge/sources")
def knowledge_delete(req: KnowledgeDeleteRequest):
    deleted = delete_document(req.source)

    return {
        "source": req.source,
        "deleted_chunks": deleted,
        "success": True,
    }


# ==========================================
# AI Chat API
# ==========================================

@app.post("/chat")
async def chat(req: ChatRequest):
    require_cloud_consent(req)

    messages = [
        message.model_dump()
        for message in req.messages
    ]

    try:
        reply = await generate_reply(
            messages,
            knowledge_source=req.knowledge_source,
            model_provider=req.model_provider,
        )

        return {
            "reply": reply,
            "model": GEMINI_MODEL if req.model_provider == "gemini" else MODEL_NAME,
            "model_provider": req.model_provider,
        }

    except GeminiConfigurationError as e:
        raise HTTPException(status_code=503, detail=str(e))

    except GeminiAPIError as e:
        raise HTTPException(status_code=502, detail=str(e))

    except OllamaConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e))

    except OllamaTimeoutError as e:
        raise HTTPException(status_code=504, detail=str(e))

    except OllamaResponseError as e:
        raise HTTPException(status_code=502, detail=str(e))


# ==========================================
# Streaming Chat API
# ==========================================


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest):

    # Require consent before starting the streaming response.
    require_cloud_consent(req)

    if not req.messages:
        raise HTTPException(
            status_code=400,
            detail="ไม่มีข้อความ",
        )

    if req.model_provider == "gemini":
        try:
            ensure_gemini_configured()
        except GeminiConfigurationError as exc:
            raise HTTPException(
                status_code=503,
                detail=str(exc),
            ) from exc

    messages = [
        message.model_dump()
        for message in req.messages
    ]

    conv_id = req.conversation_id

    if conv_id is None or not db.conversation_exists(conv_id):
        conv_id = db.create_conversation(
            req.messages[-1].content[:40],
            model_provider=req.model_provider,
        )
    else:
        db.update_conversation_model(
            conv_id,
            req.model_provider,
        )

    db.add_message(
        conv_id,
        "user",
        req.messages[-1].content,
    )

    async def generate():
        parts = []
        completed = False

        try:
            async for text in generate_stream(
                messages,
                knowledge_source=req.knowledge_source,
                model_provider=req.model_provider,
            ):
                parts.append(text)
                yield text

            completed = True

        except GeminiConfigurationError as exc:
            yield f"\n[ข้อผิดพลาด: {exc}]"

        except GeminiAPIError as exc:
            yield f"\n[ข้อผิดพลาด: {exc}]"

        except OllamaConnectionError:
            yield "\n[ข้อผิดพลาด: เชื่อมต่อ Ollama ไม่ได้]"

        except OllamaTimeoutError:
            yield "\n[ข้อผิดพลาด: Ollama ตอบช้าเกินเวลา]"

        except OllamaResponseError as exc:
            yield f"\n[ข้อผิดพลาด: {exc}]"

        except Exception:
            logger.exception("Unexpected streaming error")
            yield "\n[ข้อผิดพลาด: เกิดปัญหาระหว่างสร้างคำตอบ]"

        finally:
            if parts:
                db.add_message(
                    conv_id,
                    "assistant",
                    "".join(parts),
                )

            if completed:
                logger.info(
                    "Chat stream completed: conversation_id=%s",
                    conv_id,
                )
            else:
                logger.warning(
                    "Chat stream interrupted: conversation_id=%s",
                    conv_id,
                )

    return StreamingResponse(
        generate(),
        media_type="text/plain; charset=utf-8",
        headers={
            "X-Conversation-Id": str(conv_id),
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
