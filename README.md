# ThaiMate AI

A local AI chat assistant that runs entirely on your own computer.
Chat in Thai or English, and let the assistant write, save, and run Python code
inside a restricted workspace, with your approval at every step.

ผู้ช่วย AI ภาษาไทยที่รันบนเครื่องของคุณเอง ไม่ส่งข้อมูลออกอินเทอร์เน็ต

## Features

- Streaming chat with a local LLM through Ollama (default: `qwen3.5:4b`)
- Persistent chat history (SQLite) with a sidebar to switch conversations
- Attach files from the workspace so the model can read them
- Save code from the chat into the workspace (asks before overwriting)
- Run Python files with an explicit approval step, a 10-second timeout,
  and captured output
- Send run results back to the model so it can explain and fix errors

## Architecture

```
Browser (Next.js, port 3000)
        |
        v
FastAPI backend (port 8000) --- SQLite (thaimate.db)
        |
        +--- workspace/ (the only folder the AI can touch)
        |
        v
Ollama (port 11434) --- local model
```

- `backend/main.py` API endpoints (chat, conversations, files, run)
- `backend/db.py` SQLite storage
- `backend/workspace.py` safe file access and code execution
- `frontend/src/app/page.tsx` the chat UI

## Requirements

- Windows, Python 3.10+, Node.js 18.18+
- [Ollama](https://ollama.com) with a model pulled, e.g. `ollama pull qwen3.5:4b`
- Tested on a laptop with 16 GB RAM and an RTX 3050 (4 GB VRAM)

## Setup

Backend:

```powershell
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install fastapi uvicorn httpx
uvicorn main:app --reload
```

Frontend (new terminal):

```powershell
cd frontend
npm install
npm run dev
```

Open http://localhost:3000. Make sure Ollama is running.

To change the model, edit `MODEL_NAME` in `backend/main.py`.

## Safety design

- File access is limited to the `workspace/` folder. Paths are resolved and
  checked, so `../` tricks are rejected.
- Writing never overwrites silently; the UI asks first.
- Only a small set of text/code extensions can be written
  (no `.bat`, `.ps1`, `.exe`).
- Code is never run automatically. The UI shows the exact command, the working
  folder, and the timeout, and waits for approval.
- Execution uses a fixed command (no shell), no stdin, a 10 s timeout, and
  truncated output.

## Limitations

- **Running code is not sandboxed.** A Python script runs with the same
  permissions as your user account and can access files outside `workspace/`.
  Read the code before approving. For stronger isolation, run it in Docker or
  Windows Sandbox.
- Small local models (4B) make mistakes and may occasionally mix in Chinese
  characters. The system prompt reduces but does not eliminate this.
- Thinking mode is disabled for speed; enabling it improves reasoning but is
  much slower on 4 GB VRAM.
- No internet access, no document (PDF/Word) reading yet.

## Roadmap

- One-click launcher script
- PDF/Word reading
- Model comparison (Pathumma, Qwen3.5, Typhoon)
- Voice input (Faster-Whisper)
- Selectable working folder with stricter safety checks

## Author

Your name / GitHub link here