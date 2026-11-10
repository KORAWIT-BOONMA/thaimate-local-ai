
import json
import math
import re
import sqlite3

from contextlib import closing
from pathlib import Path

import workspace

from ai.embeddings import embed_query, embed_documents


# ==========================================
# Knowledge Database Configuration
# ==========================================

DB_PATH = Path(__file__).resolve().parent.parent / "knowledge.db"

CHUNK_SIZE = 1200
CHUNK_OVERLAP = 150

BATCH_SIZE = 8

MAX_DOCUMENT_BYTES = 200_000
MAX_QUERY_CHARS = 2_000


# Exact attachment paths supplied by the frontend. This preserves spaces
# and parentheses in filenames (for example: document (1).pdf).
ATTACHMENT_SOURCE_PATTERN = re.compile(
    r"\[เอกสารอ้างอิง:\s*(?P<source>[^\]\r\n]+)\]",
    re.IGNORECASE,
)


# ==========================================
# Supported Workspace Files
# ==========================================

SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".xlsx",
    ".txt",
    ".md",
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".html",
    ".css",
    ".json",
    ".csv",
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


# ==========================================
# Structured Table Patterns
# ==========================================

TABLE_START_PATTERN = re.compile(
    r"(?m)^\[ตารางข้อมูล:.*\]\s*$"
)

RECORD_START_PATTERN = re.compile(
    r"^\[(?:Record .+|แถวข้อมูล \d+)\]$"
)


# ==========================================
# Database
# ==========================================

def get_knowledge_conn() -> sqlite3.Connection:
    """Create a connection to the local knowledge database."""

    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row

    return conn


def init_knowledge_db():
    """Create local knowledge database."""

    with closing(get_knowledge_conn()) as conn:

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                content TEXT NOT NULL,
                embedding TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(source, chunk_index)
            )
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_knowledge_source
            ON knowledge_chunks(source)
            """
        )

        conn.commit()


# ==========================================
# Workspace File Validation
# ==========================================

def validate_workspace_file(rel_path: str) -> str:
    """Validate a file before indexing or searching it."""

    if not isinstance(rel_path, str) or not rel_path.strip():
        raise ValueError("กรุณาระบุชื่อไฟล์")

    path = workspace.safe_path(rel_path.strip())

    if not path.is_file():
        raise workspace.WorkspaceError("ไม่พบไฟล์")

    relative_path = path.relative_to(
        workspace.WORKSPACE
    )

    # Block system and dependency directories.
    if any(
        part.lower() in BLOCKED_DIRECTORIES
        for part in relative_path.parts[:-1]
    ):
        raise workspace.WorkspaceError(
            "ไม่อนุญาตให้นำเข้าไฟล์จากโฟลเดอร์ระบบ"
        )

    filename = path.name.lower()

    if any(
        part.startswith(".")
        for part in relative_path.parts
    ):
        raise workspace.WorkspaceError(
            "ไม่อนุญาตให้นำเข้าไฟล์หรือโฟลเดอร์ที่ซ่อนอยู่"
        )

    # Block environment and sensitive files.
    if (
        filename == ".env"
        or filename.startswith(".env.")
        or any(
            part in filename
            for part in SENSITIVE_FILENAME_PARTS
        )
    ):
        raise workspace.WorkspaceError(
            "ไฟล์นี้มีลักษณะเป็นไฟล์ข้อมูลลับ"
        )

    if filename in {
        "id_rsa",
        "id_ed25519",
    }:
        raise workspace.WorkspaceError(
            "ไม่อนุญาตให้นำเข้ากุญแจส่วนตัว"
        )

    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise workspace.WorkspaceError(
            "ไม่รองรับไฟล์ประเภทนี้สำหรับการค้นหา"
        )

    return relative_path.as_posix()


# ==========================================
# Resolve Explicit File References
# ==========================================

def resolve_indexed_source_from_query(
    query: str,
) -> tuple[bool, str | None]:
    """
    Detect a filename explicitly mentioned in a user query.

    Returns:
        (False, None): No filename was mentioned.
        (True, source): Exactly one indexed source was found.
        (True, None): A filename was mentioned but could not
                      be resolved uniquely.
    """

    if not isinstance(query, str) or not query.strip():
        return False, None

    # Prefer the exact path carried by the UI attachment marker.
    # A normal filename regex splits filenames containing spaces, such as "(1).pdf".
    attachment_matches = list(
        ATTACHMENT_SOURCE_PATTERN.finditer(query)
    )

    if attachment_matches:
        candidates = [
            match.group("source").replace(chr(92), "/").strip()
            for match in attachment_matches
            if match.group("source").strip()
        ]
    else:
        extensions_pattern = "|".join(
            re.escape(ext.lstrip("."))
            for ext in sorted(
                SUPPORTED_EXTENSIONS,
                key=len,
                reverse=True,
            )
        )

        file_pattern_string = (
            r'"(?P<double>[^"]+\.(?:'
            + extensions_pattern
            + r'))"'
            r"|'(?P<single>[^']+\.(?:"
            + extensions_pattern
            + r"))'"
            r'''|(?P<bare>[^\s"'<>]+\.(?:'''
            + extensions_pattern
            + r'''))(?=$|[\s,;:!?.)}\]])'''
        )

        file_pattern = re.compile(
            file_pattern_string,
            re.IGNORECASE,
        )

        candidates = []

        for match in file_pattern.finditer(query):

            candidate = (
                match.group("double")
                or match.group("single")
                or match.group("bare")
            )

            if candidate:

                candidates.append(
                    candidate.replace("\\", "/").strip()
                )

        if not candidates:
            return False, None

    # Remove duplicate references while preserving their order.
    candidates = list(dict.fromkeys(candidates))

    if not candidates:
        return False, None

    init_knowledge_db()

    with closing(get_knowledge_conn()) as conn:

        rows = conn.execute(
            """
            SELECT DISTINCT source
            FROM knowledge_chunks
            """
        ).fetchall()

    indexed_sources = [
        str(row["source"])
        for row in rows
    ]

    resolved_sources = []

    for candidate in candidates:

        if "/" in candidate:

            matches = [
                source
                for source in indexed_sources
                if source.replace("\\", "/").casefold()
                == candidate.casefold()
            ]

        else:

            matches = [
                source
                for source in indexed_sources
                if source.rsplit("/", 1)[-1].casefold()
                == candidate.casefold()
            ]

        # Never guess when a file is missing
        # or multiple indexed files share the same name.
        if len(matches) != 1:
            return True, None

        resolved_sources.append(matches[0])

    unique_sources = set(resolved_sources)

    # One request must resolve to exactly one file.
    if len(unique_sources) != 1:
        return True, None

    return True, resolved_sources[0]


# ==========================================
# Structured Table Chunking
# ==========================================

def _split_structured_table_block(
    table_text: str,
    chunk_size: int,
) -> list[str]:
    """
    Split a structured table using complete record boundaries.

    Each chunk keeps the original table header.
    Individual records are never divided between chunks.
    """

    lines = table_text.strip().splitlines()

    if not lines:
        return []

    record_positions = [
        index
        for index, line in enumerate(lines)
        if RECORD_START_PATTERN.fullmatch(line.strip())
    ]

    # Keep header-only tables as one chunk.
    if not record_positions:
        return [table_text.strip()]

    # Everything before the first record is shared metadata.
    header = "\n".join(
        lines[:record_positions[0]]
    ).strip()

    records = []

    for index, start in enumerate(record_positions):

        end = (
            record_positions[index + 1]
            if index + 1 < len(record_positions)
            else len(lines)
        )

        record = "\n".join(
            lines[start:end]
        ).strip()

        if record:
            records.append(record)

    def build_chunk(items: list[str]) -> str:

        return "\n\n".join(
            part
            for part in [header, *items]
            if part
        )

    chunks = []
    current_records = []

    for record in records:

        candidate_records = current_records + [record]
        candidate = build_chunk(candidate_records)

        # Start a new chunk only between complete records.
        if current_records and len(candidate) > chunk_size:

            chunks.append(
                build_chunk(current_records)
            )

            current_records = [record]

        else:
            current_records = candidate_records

    if current_records:

        chunks.append(
            build_chunk(current_records)
        )

    return chunks


def _split_structured_tables(
    text: str,
    chunk_size: int,
) -> list[str] | None:
    """
    Detect and split CSV/XLSX-style structured tables.

    Returns None when no recognized structured table exists.
    """

    matches = list(
        TABLE_START_PATTERN.finditer(text)
    )

    if not matches:
        return None

    chunks = []

    prefix = text[:matches[0].start()].strip()

    for index, match in enumerate(matches):

        start = match.start()

        end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else len(text)
        )

        table_block = text[start:end].strip()

        # Preserve text before the first table.
        if index == 0 and prefix:
            table_block = prefix + "\n\n" + table_block

        table_chunks = _split_structured_table_block(
            table_block,
            chunk_size,
        )

        if not table_chunks:
            return None

        chunks.extend(table_chunks)

    return chunks if chunks else None


# ==========================================
# Text Processing
# ==========================================

def split_text(
    text: str,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[str]:
    """
    Split documents into searchable chunks.

    Structured tables:
        Split between complete records and repeat headers.

    Regular documents:
        Keep the original character-based overlapping split.
    """

    text = text.strip()

    if not text:
        return []

    if (
        chunk_size <= 0
        or overlap < 0
        or overlap >= chunk_size
    ):
        raise ValueError("Chunk configuration is invalid")

    # Handle structured tables first.
    structured_chunks = _split_structured_tables(
        text,
        chunk_size,
    )

    if structured_chunks is not None:
        return structured_chunks

    # Original behavior for regular text, PDF and DOCX.
    chunks = []
    start = 0

    while start < len(text):

        end = min(start + chunk_size, len(text))

        # Prefer breaking at a newline.
        if end < len(text):

            boundary = text.rfind("\n", start, end)

            if boundary > start + chunk_size // 2:
                end = boundary

        chunk = text[start:end].strip()

        if chunk:
            chunks.append(chunk)

        if end >= len(text):
            break

        start = end - overlap

    return chunks


# ==========================================
# Index Documents
# ==========================================

async def index_document(
    source: str,
    content: str,
) -> int:
    """
    Convert document content into embeddings
    and save them in the local knowledge database.

    Existing chunks from the same source are replaced
    only after all embeddings have been generated.
    """

    init_knowledge_db()

    source = source.strip()

    if not source:
        raise ValueError("Document source cannot be empty")

    if not isinstance(content, str) or not content.strip():
        raise ValueError("Document content is empty")

    if len(content.encode("utf-8")) > MAX_DOCUMENT_BYTES:
        raise ValueError("เอกสารมีขนาดใหญ่เกินไป")

    chunks = split_text(content)

    if not chunks:
        raise ValueError("Document content is empty")

    records = []

    # Generate embeddings before opening the write transaction.
    for start in range(0, len(chunks), BATCH_SIZE):

        batch = chunks[start:start + BATCH_SIZE]

        vectors = await embed_documents(
            batch,
            keep_alive="30s",
        )

        if len(vectors) != len(batch):
            raise ValueError("Embedding count mismatch")

        for i, (chunk, vector) in enumerate(
            zip(batch, vectors)
        ):

            if not isinstance(vector, list) or not vector:
                raise ValueError("Invalid embedding vector")

            records.append(
                (
                    source,
                    start + i,
                    chunk,
                    json.dumps(vector),
                )
            )

    # Replace old document data atomically.
    conn = get_knowledge_conn()

    try:

        conn.execute("BEGIN")

        conn.execute(
            "DELETE FROM knowledge_chunks WHERE source = ?",
            (source,),
        )

        conn.executemany(
            """
            INSERT INTO knowledge_chunks
            (source, chunk_index, content, embedding)
            VALUES (?, ?, ?, ?)
            """,
            records,
        )

        conn.commit()

        return len(chunks)

    except Exception:

        conn.rollback()
        raise

    finally:
        conn.close()


# ==========================================
# Vector Similarity
# ==========================================

def cosine_similarity(
    vector_a: list[float],
    vector_b: list[float],
) -> float:
    """Calculate cosine similarity between two vectors."""

    if len(vector_a) != len(vector_b):
        return 0.0

    dot = math.fsum(
        a * b for a, b in zip(vector_a, vector_b)
    )

    norm_a = math.sqrt(
        math.fsum(a * a for a in vector_a)
    )

    norm_b = math.sqrt(
        math.fsum(b * b for b in vector_b)
    )

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot / (norm_a * norm_b)


# ==========================================
# Search Knowledge
# ==========================================

async def search_knowledge(
    query: str,
    top_k: int = 5,
    source: str | None = None,
    include_all_chunks: bool = False,
) -> list[dict]:
    """
    Search local knowledge.

    Normal search:
        Return the highest-ranking top_k chunks
        using BGE-M3 embeddings.

    Full file search:
        Return every stored chunk from one validated source
        directly from SQLite, ordered by chunk_index.
        No embedding or similarity calculation is required.
    """

    init_knowledge_db()

    if not isinstance(query, str):
        raise ValueError("คำค้นหาไม่ถูกต้อง")

    query = query.strip()

    if not query:
        return []

    if len(query) > MAX_QUERY_CHARS:
        raise ValueError("คำค้นหายาวเกินไป")

    top_k = max(1, min(top_k, 10))

    if include_all_chunks and source is None:
        raise ValueError(
            "การดึงทุก Chunk ต้องระบุไฟล์ต้นทาง"
        )

    if source is not None:
        source = validate_workspace_file(source)

    # --------------------------------------
    # Full File Retrieval
    # --------------------------------------
    # Retrieve all stored chunks directly from SQLite.
    # Do not load BGE-M3 or calculate cosine similarity.
    # This prevents chunks from being skipped because
    # of missing or corrupted embedding data.

    if include_all_chunks:

        with closing(get_knowledge_conn()) as conn:

            rows = conn.execute(
                """
                SELECT
                    source,
                    chunk_index,
                    content
                FROM knowledge_chunks
                WHERE source = ?
                ORDER BY chunk_index ASC
                """,
                (source,),
            ).fetchall()

        return [
            {
                "source": row["source"],
                "chunk_index": row["chunk_index"],
                "content": row["content"],
                "score": 1.0,
            }
            for row in rows
        ]

    # --------------------------------------
    # Normal Search: Check Indexed Documents
    # --------------------------------------

    with closing(get_knowledge_conn()) as conn:

        if source is None:

            has_documents = conn.execute(
                """
                SELECT 1
                FROM knowledge_chunks
                LIMIT 1
                """
            ).fetchone()

        else:

            has_documents = conn.execute(
                """
                SELECT 1
                FROM knowledge_chunks
                WHERE source = ?
                LIMIT 1
                """,
                (source,),
            ).fetchone()

    if has_documents is None:
        return []

    # --------------------------------------
    # Normal Search: BGE-M3 Embedding
    # --------------------------------------

    query_vector = await embed_query(query)

    results = []

    conn = get_knowledge_conn()

    try:

        if source is None:

            cursor = conn.execute(
                """
                SELECT source, chunk_index, content, embedding
                FROM knowledge_chunks
                """
            )

        else:

            cursor = conn.execute(
                """
                SELECT source, chunk_index, content, embedding
                FROM knowledge_chunks
                WHERE source = ?
                """,
                (source,),
            )

        for row in cursor:

            try:

                document_vector = json.loads(
                    row["embedding"]
                )

                if not isinstance(document_vector, list):
                    continue

                score = cosine_similarity(
                    query_vector,
                    document_vector,
                )

            except (
                json.JSONDecodeError,
                TypeError,
                ValueError,
            ):
                continue

            results.append(
                {
                    "source": row["source"],
                    "chunk_index": row["chunk_index"],
                    "content": row["content"],
                    "score": round(score, 4),
                }
            )

    finally:
        conn.close()

    # --------------------------------------
    # Normal Top-K Retrieval
    # --------------------------------------

    results.sort(
        key=lambda item: item["score"],
        reverse=True,
    )

    return results[:top_k]


# ==========================================
# Knowledge Management
# ==========================================

def delete_document(source: str) -> int:
    """Delete all indexed chunks from a document."""

    init_knowledge_db()

    with closing(get_knowledge_conn()) as conn:

        cursor = conn.execute(
            """
            DELETE FROM knowledge_chunks
            WHERE source = ?
            """,
            (source.strip(),),
        )

        deleted_count = cursor.rowcount

        conn.commit()

        return deleted_count


def list_knowledge_sources() -> list[dict]:
    """List all indexed documents."""

    init_knowledge_db()

    with closing(get_knowledge_conn()) as conn:

        rows = conn.execute(
            """
            SELECT
                source,
                COUNT(*) AS chunks,
                MAX(created_at) AS indexed_at
            FROM knowledge_chunks
            GROUP BY source
            ORDER BY source
            """
        ).fetchall()

        return [dict(row) for row in rows]


# ==========================================
# Workspace File Indexing
# ==========================================

async def index_workspace_file(
    rel_path: str,
) -> dict:
    """Read a real Workspace file and index its content."""

    source = validate_workspace_file(rel_path)

    content = workspace.read_file(source)

    if not content.strip():
        raise ValueError("ไฟล์ไม่มีเนื้อหา")

    chunk_count = await index_document(
        source=source,
        content=content,
    )

    return {
        "source": source,
        "chunks": chunk_count,
        "status": "indexed",
    }
