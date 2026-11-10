
import os
import uuid
from pathlib import Path, PurePosixPath


# ==========================================
# Workspace Configuration
# ==========================================

WORKSPACE = (Path(__file__).parent.parent / "workspace").resolve()

MAX_READ_BYTES = 10 * 1024 * 1024
MAX_WRITE_BYTES = 200_000
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

UPLOAD_DIRECTORY = "uploads"

UPLOAD_ALLOWED_EXTENSIONS = {
    ".pdf", ".docx", ".txt", ".csv", ".xlsx",
    ".md", ".py", ".js", ".ts", ".tsx", ".jsx",
    ".html", ".css", ".json",
}

BLOCKED_DIRECTORIES = {
    ".git",
    "node_modules",
    "venv",
    ".venv",
    "__pycache__",
    ".next",
    "dist",
    "build",
    ".pytest_cache",
    ".cache",
}

SENSITIVE_FILENAME_PARTS = {
    "secret",
    "credential",
    "token",
    "password",
}

ALLOWED_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".json",
    ".md", ".txt", ".html", ".css",
}


class WorkspaceError(Exception):
    """Workspace access or operation error."""


class FileExistsConflict(WorkspaceError):
    """Raised when a file already exists."""


# ==========================================
# Workspace Path Validation
# ==========================================

def safe_path(rel: str) -> Path:
    """
    Resolve a relative path and prevent traversal,
    absolute-path access and symlink escapes.
    """

    if not isinstance(rel, str) or not rel.strip():
        raise WorkspaceError("กรุณาระบุ path ของไฟล์")

    rel = rel.strip()

    if "\x00" in rel:
        raise WorkspaceError("Path ไม่ถูกต้อง")

    raw_path = Path(rel)

    if raw_path.is_absolute() or raw_path.drive:
        raise WorkspaceError(
            "อนุญาตเฉพาะ path ที่อยู่ภายใน Workspace"
        )

    if ".." in raw_path.parts:
        raise WorkspaceError(
            "ไม่อนุญาตให้ใช้ path traversal"
        )

    candidate = WORKSPACE / raw_path

    # Reject symbolic links in every existing path component.
    current = candidate

    while current != WORKSPACE:

        if current.is_symlink():
            raise WorkspaceError(
                "ไม่อนุญาตให้เข้าถึงไฟล์ผ่าน Symbolic Link"
            )

        current = current.parent

    try:
        target = candidate.resolve()

    except (OSError, RuntimeError, ValueError) as exc:
        raise WorkspaceError(
            "ไม่สามารถตรวจสอบ path ได้"
        ) from exc

    if target != WORKSPACE and WORKSPACE not in target.parents:
        raise WorkspaceError("path อยู่นอก Workspace")

    return target


def _is_sensitive_path(relative_path: Path) -> bool:
    """Detect hidden, sensitive and system paths."""

    parts = tuple(
        part.lower()
        for part in relative_path.parts
    )

    filename = relative_path.name.lower()

    # Block hidden files and directories.
    if any(part.startswith(".") for part in parts):
        return True

    # Block system and dependency directories.
    if any(
        part in BLOCKED_DIRECTORIES
        for part in parts[:-1]
    ):
        return True

    # Block environment files.
    if filename == ".env" or filename.startswith(".env."):
        return True

    # Block filenames that may contain credentials.
    if any(
        keyword in filename
        for keyword in SENSITIVE_FILENAME_PARTS
    ):
        return True

    # Block common private key files.
    if filename in {
        "id_rsa",
        "id_ed25519",
    }:
        return True

    return False


def _validate_accessible_path(
    path: Path,
    *,
    allow_uploads: bool = True,
) -> Path:
    """Validate a resolved path before accessing its contents."""

    try:
        relative = path.relative_to(WORKSPACE)

    except ValueError as exc:
        raise WorkspaceError(
            "path อยู่นอก Workspace"
        ) from exc

    if _is_sensitive_path(relative):
        raise WorkspaceError(
            "ไม่อนุญาตให้เข้าถึงไฟล์ลับหรือโฟลเดอร์ระบบ"
        )

    if (
        not allow_uploads
        and relative.parts
        and relative.parts[0].casefold() == UPLOAD_DIRECTORY.casefold()
    ):
        raise WorkspaceError(
            "ไม่อนุญาตให้ดำเนินการกับไฟล์ภายใน Upload Directory"
        )

    return path


def _validate_filename(filename: str) -> str:
    """Validate a filename for safe local storage."""

    normalized = PurePosixPath(
        filename.replace("\\", "/")
    ).name.strip()

    if (
        not normalized
        or normalized in {".", ".."}
        or normalized.startswith(".")
    ):
        raise WorkspaceError("ชื่อไฟล์ไม่ถูกต้อง")

    if any(ord(char) < 32 for char in normalized):
        raise WorkspaceError("ชื่อไฟล์มีอักขระที่ไม่อนุญาต")

    if any(
        char in '<>:"|?*'
        for char in normalized
    ):
        raise WorkspaceError("ชื่อไฟล์มีอักขระที่ไม่รองรับ")

    # Windows reserved filenames.
    stem = Path(normalized).stem.upper()

    reserved_names = {
        "CON", "PRN", "AUX", "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }

    if stem in reserved_names:
        raise WorkspaceError("ชื่อไฟล์นี้สงวนไว้โดยระบบ")

    return normalized


# ==========================================
# List Workspace Files
# ==========================================

def list_files() -> list[str]:
    """List ordinary workspace files without exposing hidden/system files."""

    WORKSPACE.mkdir(parents=True, exist_ok=True)

    files: list[str] = []

    for current_root, directory_names, filenames in os.walk(WORKSPACE):

        root_path = Path(current_root)

        directory_names[:] = sorted(
            name
            for name in directory_names
            if (
                not name.startswith(".")
                and name.lower() not in BLOCKED_DIRECTORIES
                and not (root_path / name).is_symlink()
            )
        )

        for filename in filenames:

            file_path = root_path / filename

            if file_path.is_symlink():
                continue

            try:
                relative = file_path.relative_to(WORKSPACE)

            except ValueError:
                continue

            if _is_sensitive_path(relative):
                continue

            if not file_path.is_file():
                continue

            files.append(relative.as_posix())

    return sorted(files)


# ==========================================
# Read Workspace Files
# ==========================================

def read_file(rel: str) -> str:
    """Read a supported text/document file from Workspace."""

    path = safe_path(rel)

    _validate_accessible_path(path)

    if not path.is_file():
        raise WorkspaceError("ไม่พบไฟล์")

    if path.stat().st_size > MAX_READ_BYTES:
        raise WorkspaceError(
            "ไฟล์ใหญ่เกินไป (สูงสุด 10 MB)"
        )

    # Lazy import avoids a module-level circular dependency.
    from ai.document_reader import (
        DocumentReadError,
        extract_document_text,
    )

    try:
        return extract_document_text(path)

    except DocumentReadError as exc:
        raise WorkspaceError(str(exc)) from exc


# ==========================================
# Upload / Delete User Documents
# ==========================================

def save_uploaded_file(
    filename: str,
    content: bytes,
    overwrite: bool = False,
) -> dict:
    """Save an uploaded document atomically under workspace/uploads."""

    if not isinstance(content, bytes):
        raise WorkspaceError("ข้อมูลไฟล์ไม่ถูกต้อง")

    normalized_name = _validate_filename(filename)

    suffix = Path(normalized_name).suffix.lower()

    if suffix not in UPLOAD_ALLOWED_EXTENSIONS:
        raise WorkspaceError(
            "ไม่รองรับไฟล์นี้ รองรับ PDF, DOCX, TXT, CSV, XLSX "
            "และไฟล์ข้อความ/โค้ดทั่วไป"
        )

    if not content:
        raise WorkspaceError("ไฟล์ว่างเปล่า")

    if len(content) > MAX_UPLOAD_BYTES:
        raise WorkspaceError("ไฟล์มีขนาดเกิน 10 MB")

    relative = f"{UPLOAD_DIRECTORY}/{normalized_name}"

    target = safe_path(relative)
    target.parent.mkdir(parents=True, exist_ok=True)

    # Resolve again after creating the directory.
    target = safe_path(relative)
    _validate_accessible_path(target)

    existed = target.exists()

    if existed and not overwrite:
        raise FileExistsConflict(
            "มีไฟล์ชื่อนี้อยู่แล้ว ต้องยืนยันการแทนที่ไฟล์เดิม"
        )

    if existed and not target.is_file():
        raise WorkspaceError("ชื่อปลายทางนี้ไม่ใช่ไฟล์")

    if existed and target.is_symlink():
        raise WorkspaceError("ไม่อนุญาตให้แทนที่ Symbolic Link")

    temporary = target.with_name(
        f".{target.name}.{uuid.uuid4().hex}.upload"
    )

    try:

        with temporary.open("xb") as stream:

            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())

        os.replace(temporary, target)

    except OSError as exc:

        try:
            temporary.unlink(missing_ok=True)

        except OSError:
            pass

        raise WorkspaceError(
            f"บันทึกไฟล์ไม่สำเร็จ: {exc}"
        ) from exc

    return {
        "path": relative,
        "filename": normalized_name,
        "size": len(content),
        "created": not existed,
    }


def delete_uploaded_file(rel: str) -> dict:
    """Delete only files uploaded into workspace/uploads."""

    path = safe_path(rel)

    if not path.is_file():
        raise WorkspaceError("ไม่พบไฟล์")

    relative = path.relative_to(WORKSPACE)

    if (
        not relative.parts
        or relative.parts[0].casefold() != UPLOAD_DIRECTORY.casefold()
    ):
        raise WorkspaceError(
            "ลบได้เฉพาะไฟล์ที่อัปโหลดเข้าระบบผ่าน ThaiMate"
        )

    _validate_accessible_path(path)

    path.unlink()

    return {
        "path": relative.as_posix(),
        "deleted": True,
    }


# ==========================================
# Write Generated Code / Text Files
# ==========================================

def write_file(
    rel: str,
    content: str,
    overwrite: bool = False,
) -> dict:
    """Save generated text/code atomically inside Workspace."""

    path = safe_path(rel)

    _validate_accessible_path(
        path,
        allow_uploads=False,
    )

    if path == WORKSPACE or path.is_dir():
        raise WorkspaceError("ต้องระบุชื่อไฟล์")

    if path.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise WorkspaceError(
            "นามสกุลไฟล์นี้ไม่อนุญาต (ใช้ได้: "
            + ", ".join(sorted(ALLOWED_EXTENSIONS))
            + ")"
        )

    if not isinstance(content, str):
        raise WorkspaceError("เนื้อหาไฟล์ต้องเป็นข้อความ")

    encoded = content.encode("utf-8")

    if len(encoded) > MAX_WRITE_BYTES:
        raise WorkspaceError("เนื้อหายาวเกินไป")

    path.parent.mkdir(parents=True, exist_ok=True)

    # Resolve again after directory creation.
    path = safe_path(rel)

    _validate_accessible_path(
        path,
        allow_uploads=False,
    )

    existed = path.exists()

    if existed and not overwrite:
        raise FileExistsConflict(
            "ไฟล์นี้มีอยู่แล้ว ต้องยืนยันการทับไฟล์"
        )

    if existed and not path.is_file():
        raise WorkspaceError("ปลายทางไม่ใช่ไฟล์ปกติ")

    temporary = path.with_name(
        f".{path.name}.{uuid.uuid4().hex}.tmp"
    )

    try:

        with temporary.open(
            "x",
            encoding="utf-8",
            newline="",
        ) as stream:

            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())

        os.replace(temporary, path)

    except OSError as exc:

        try:
            temporary.unlink(missing_ok=True)

        except OSError:
            pass

        raise WorkspaceError(
            f"บันทึกไฟล์ไม่สำเร็จ: {exc}"
        ) from exc

    return {
        "path": path.relative_to(WORKSPACE).as_posix(),
        "created": not existed,
    }


# ==========================================
# Python Execution
# ==========================================

RUN_TIMEOUT = 10
MAX_OUTPUT_CHARS = 20_000

# IMPORTANT:
# Arbitrary Python code cannot be securely sandboxed merely by running
# it as a subprocess. A child process normally inherits the same OS
# permissions and may access files outside Workspace.
#
# Code execution therefore remains disabled until a real isolated
# execution environment is implemented.

RUN_EXECUTION_ENABLED = False


def _resolve_runnable(rel: str) -> Path:
    """Validate a generated Python file before showing its preview."""

    path = safe_path(rel)

    _validate_accessible_path(
        path,
        allow_uploads=False,
    )

    if not path.is_file():
        raise WorkspaceError("ไม่พบไฟล์")

    if path.suffix.lower() != ".py":
        raise WorkspaceError("รันได้เฉพาะไฟล์ .py")

    return path


def run_preview(rel: str) -> dict:
    """Preview a Python command without executing it."""

    path = _resolve_runnable(rel)

    name = path.relative_to(WORKSPACE).as_posix()

    return {
        "command": f"python {name}",
        "cwd": str(WORKSPACE),
        "timeout_seconds": RUN_TIMEOUT,
        "execution_enabled": RUN_EXECUTION_ENABLED,
        "warning": (
            "การรันโค้ดถูกปิดไว้ชั่วคราว "
            "จนกว่าจะติดตั้งระบบ Sandbox ที่จำกัดสิทธิ์การเข้าถึงจริง"
        ),
    }


def run_file(rel: str) -> dict:
    """
    Execution intentionally disabled.

    Do not replace this with subprocess.run under the backend user's
    permissions and assume that it is a security sandbox.
    """

    _resolve_runnable(rel)

    raise WorkspaceError(
        "ปิดการรัน Python ชั่วคราวเพื่อความปลอดภัย "
        "ระบบยังสามารถสร้าง บันทึก อ่าน และ Preview โค้ดได้ "
        "แต่ต้องติดตั้งระบบ Isolated Sandbox ก่อนจึงจะอนุญาตให้รันได้"
    )
