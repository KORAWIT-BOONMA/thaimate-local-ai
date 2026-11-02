import os
import subprocess
import sys
from pathlib import Path

# โฟลเดอร์ที่ AI ทำงานได้ (thaimate/workspace) ห้ามออกนอกที่นี่
WORKSPACE = (Path(__file__).parent.parent / "workspace").resolve()
MAX_READ_BYTES = 200_000  # กันอ่านไฟล์ใหญ่เกินไป


class WorkspaceError(Exception):
    pass


def safe_path(rel: str) -> Path:
    """แปลง path ที่ได้รับเป็น path จริง และตรวจว่าอยู่ใน Workspace เท่านั้น"""
    target = (WORKSPACE / rel).resolve()
    if target != WORKSPACE and WORKSPACE not in target.parents:
        raise WorkspaceError("path อยู่นอก Workspace")
    return target


def list_files():
    files = []
    for p in sorted(WORKSPACE.rglob("*")):
        if p.is_file():
            files.append(str(p.relative_to(WORKSPACE)).replace("\\", "/"))
    return files


def read_file(rel: str) -> str:
    p = safe_path(rel)
    if not p.is_file():
        raise WorkspaceError("ไม่พบไฟล์")
    if p.stat().st_size > MAX_READ_BYTES:
        raise WorkspaceError("ไฟล์ใหญ่เกินไป")
    try:
        return p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise WorkspaceError("อ่านไฟล์นี้เป็นข้อความไม่ได้")


# ---------- เขียนไฟล์ ----------

ALLOWED_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx",
    ".json", ".md", ".txt", ".html", ".css",
}
MAX_WRITE_BYTES = 200_000


class FileExistsConflict(WorkspaceError):
    pass


def write_file(rel: str, content: str, overwrite: bool = False) -> dict:
    p = safe_path(rel)
    if p == WORKSPACE or p.is_dir():
        raise WorkspaceError("ต้องระบุชื่อไฟล์")
    if p.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise WorkspaceError(
            "นามสกุลไฟล์นี้ไม่อนุญาต (ใช้ได้: "
            + ", ".join(sorted(ALLOWED_EXTENSIONS))
            + ")"
        )
    if len(content.encode("utf-8")) > MAX_WRITE_BYTES:
        raise WorkspaceError("เนื้อหายาวเกินไป")

    existed = p.exists()
    if existed and not overwrite:
        raise FileExistsConflict("ไฟล์นี้มีอยู่แล้ว ต้องยืนยันการทับไฟล์")

    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return {
        "path": str(p.relative_to(WORKSPACE)).replace("\\", "/"),
        "created": not existed,
    }


# ---------- รันโค้ด ----------

RUN_TIMEOUT = 10  # วินาที
MAX_OUTPUT_CHARS = 20_000


def _resolve_runnable(rel: str) -> Path:
    p = safe_path(rel)
    if not p.is_file():
        raise WorkspaceError("ไม่พบไฟล์")
    if p.suffix.lower() != ".py":
        raise WorkspaceError("รันได้เฉพาะไฟล์ .py")
    return p


def run_preview(rel: str) -> dict:
    p = _resolve_runnable(rel)
    name = str(p.relative_to(WORKSPACE)).replace("\\", "/")
    return {
        "command": f"python {name}",
        "cwd": str(WORKSPACE),
        "timeout_seconds": RUN_TIMEOUT,
    }


def _clip(text: str) -> str:
    if len(text) > MAX_OUTPUT_CHARS:
        return text[:MAX_OUTPUT_CHARS] + "\n...[ตัดข้อความที่ยาวเกิน]"
    return text


def run_file(rel: str) -> dict:
    p = _resolve_runnable(rel)
    name = str(p.relative_to(WORKSPACE))
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    try:
        r = subprocess.run(
            [sys.executable, name],
            cwd=WORKSPACE,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=RUN_TIMEOUT,
            stdin=subprocess.DEVNULL,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return {
            "exit_code": None,
            "timed_out": True,
            "stdout": "",
            "stderr": f"หยุดโปรแกรมเพราะรันเกิน {RUN_TIMEOUT} วินาที",
        }
    return {
        "exit_code": r.returncode,
        "timed_out": False,
        "stdout": _clip(r.stdout),
        "stderr": _clip(r.stderr),
    }