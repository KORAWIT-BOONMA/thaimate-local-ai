import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "thaimate.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Create tables and safely migrate older ThaiMate databases."""
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL DEFAULT 'บทสนทนาใหม่',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                model_provider TEXT NOT NULL DEFAULT 'ollama'
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL
                    REFERENCES conversations(id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

        # Existing users already have a conversations table without this column.
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(conversations)").fetchall()
        }
        if "model_provider" not in columns:
            conn.execute(
                "ALTER TABLE conversations ADD COLUMN model_provider TEXT NOT NULL DEFAULT 'ollama'"
            )


def create_conversation(title="บทสนทนาใหม่", model_provider="ollama"):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO conversations (title, model_provider) VALUES (?, ?)",
            (title, model_provider),
        )
        return cur.lastrowid


def add_message(conversation_id, role, content):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO messages (conversation_id, role, content) VALUES (?, ?, ?)",
            (conversation_id, role, content),
        )


def get_messages(conversation_id):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY id",
            (conversation_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def list_conversations():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, title, created_at, model_provider FROM conversations ORDER BY id DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def conversation_exists(conversation_id: int) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
        return row is not None


def update_conversation_model(conversation_id: int, model_provider: str) -> bool:
    with get_conn() as conn:
        cursor = conn.execute(
            "UPDATE conversations SET model_provider = ? WHERE id = ?",
            (model_provider, conversation_id),
        )
        return cursor.rowcount > 0


def delete_conversation(conversation_id: int) -> bool:
    """Delete a conversation; SQLite cascades the delete to its messages."""
    with get_conn() as conn:
        cursor = conn.execute(
            "DELETE FROM conversations WHERE id = ?",
            (conversation_id,),
        )
        return cursor.rowcount > 0


def delete_all_conversations() -> int:
    """Delete all conversations and related messages, but not knowledge files."""
    with get_conn() as conn:
        cursor = conn.execute("DELETE FROM conversations")
        return cursor.rowcount
