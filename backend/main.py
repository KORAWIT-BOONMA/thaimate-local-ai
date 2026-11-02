import json

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import db
import workspace

app = FastAPI(title="ThaiMate AI")

# อนุญาตเฉพาะหน้าเว็บของเรา (พอร์ต 3000) ให้เรียก Backend ได้
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Conversation-Id"],
)

# ตั้งค่าไว้ที่เดียว ถ้าอยากเปลี่ยนโมเดลภายหลัง แก้ตรงนี้จุดเดียว
MODEL_NAME = "qwen3.5:4b"
OLLAMA_URL = "http://localhost:11434"

# คำสั่งกำหนดบทบาทให้โมเดล
SYSTEM_PROMPT = (
    "You are ThaiMate, a coding and general assistant running locally on the user's machine. "
    "LANGUAGE RULES (very important): "
    "Reply ONLY in Thai or English. NEVER use Chinese characters. "
    "If the user writes Thai, reply in Thai. If the user writes English, reply in English. "
    "Write code comments in English. "
    "When speaking Thai, refer to yourself as 'ผม' and end sentences with 'ครับ'. "
    "Put code in Markdown code blocks and explain briefly. "
    "Use information from earlier in the conversation, such as the user's name. "
    "If unsure, say so honestly."
)


@app.on_event("startup")
def startup():
    db.init_db()


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[Message]
    conversation_id: int | None = None


class WriteRequest(BaseModel):
    path: str
    content: str
    overwrite: bool = False


class RunRequest(BaseModel):
    path: str
    approved: bool = False


def build_messages(req: ChatRequest):
    return [{"role": "system", "content": SYSTEM_PROMPT}] + [
        m.model_dump() for m in req.messages
    ]


@app.get("/")
def root():
    return {"message": "ThaiMate ทำงานอยู่", "model": MODEL_NAME}


@app.get("/conversations")
def conversations():
    return db.list_conversations()


@app.get("/conversations/{conversation_id}/messages")
def conversation_messages(conversation_id: int):
    return db.get_messages(conversation_id)


@app.get("/files")
def files():
    return workspace.list_files()


@app.get("/files/read")
def files_read(path: str):
    try:
        return {"path": path, "content": workspace.read_file(path)}
    except workspace.WorkspaceError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/files/write")
def files_write(req: WriteRequest):
    try:
        return workspace.write_file(req.path, req.content, req.overwrite)
    except workspace.FileExistsConflict as e:
        raise HTTPException(status_code=409, detail=str(e))
    except workspace.WorkspaceError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/run/preview")
def run_preview(path: str):
    try:
        return workspace.run_preview(path)
    except workspace.WorkspaceError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/run")
def run(req: RunRequest):
    if not req.approved:
        raise HTTPException(status_code=403, detail="ต้องได้รับการอนุมัติก่อนรัน")
    try:
        return workspace.run_file(req.path)
    except workspace.WorkspaceError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/chat")
async def chat(req: ChatRequest):
    payload = {
        "model": MODEL_NAME,
        "messages": build_messages(req),
        "stream": False,
        "think": False,
    }
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(f"{OLLAMA_URL}/api/chat", json=payload)
            r.raise_for_status()
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="เชื่อมต่อ Ollama ไม่ได้ ตรวจว่า Ollama รันอยู่")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"Ollama ตอบ error: {e.response.text}")
    except httpx.ReadTimeout:
        raise HTTPException(status_code=504, detail="Ollama ตอบช้าเกินเวลาที่กำหนด")

    data = r.json()
    return {"reply": data["message"]["content"], "model": MODEL_NAME}


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    if not req.messages:
        raise HTTPException(status_code=400, detail="ไม่มีข้อความ")

    # แชตใหม่: สร้างบทสนทนา ใช้ข้อความแรกเป็นชื่อ (ตัดที่ 40 ตัวอักษร)
    conv_id = req.conversation_id
    if conv_id is None:
        conv_id = db.create_conversation(req.messages[-1].content[:40])

    # บันทึกข้อความล่าสุดของผู้ใช้
    db.add_message(conv_id, "user", req.messages[-1].content)

    payload = {
        "model": MODEL_NAME,
        "messages": build_messages(req),
        "stream": True,
        "think": False,
    }

    async def generate():
        parts = []
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                async with client.stream(
                    "POST", f"{OLLAMA_URL}/api/chat", json=payload
                ) as r:
                    if r.status_code != 200:
                        yield "[ข้อผิดพลาด: Ollama ตอบกลับผิดปกติ]"
                        return
                    async for line in r.aiter_lines():
                        if not line:
                            continue
                        chunk = json.loads(line)
                        text = chunk.get("message", {}).get("content", "")
                        if text:
                            parts.append(text)
                            yield text
        except httpx.ConnectError:
            yield "[ข้อผิดพลาด: เชื่อมต่อ Ollama ไม่ได้]"
        except httpx.ReadTimeout:
            yield "[ข้อผิดพลาด: Ollama ตอบช้าเกินเวลา]"
        finally:
            # บันทึกคำตอบเต็มของ AI (ถ้ามี) หลังสตรีมจบ
            if parts:
                db.add_message(conv_id, "assistant", "".join(parts))

    return StreamingResponse(
        generate(),
        media_type="text/plain; charset=utf-8",
        headers={"X-Conversation-Id": str(conv_id)},
    )