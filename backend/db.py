import json
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
                images_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS conversation_summaries (
                conversation_id INTEGER PRIMARY KEY
                    REFERENCES conversations(id) ON DELETE CASCADE,
                summary TEXT NOT NULL DEFAULT '',
                summarized_through_message_id INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
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

        message_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(messages)").fetchall()
        }
        if "images_json" not in message_columns:
            conn.execute(
                "ALTER TABLE messages ADD COLUMN images_json TEXT NOT NULL DEFAULT '[]'"
            )


def create_conversation(title="บทสนทนาใหม่", model_provider="ollama"):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO conversations (title, model_provider) VALUES (?, ?)",
            (title, model_provider),
        )
        return cur.lastrowid


def add_message(conversation_id, role, content, images=None):
    """Persist a chat message and its optional image attachments."""
    images_json = json.dumps(images or [], ensure_ascii=False)
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO messages (conversation_id, role, content, images_json) VALUES (?, ?, ?, ?)",
            (conversation_id, role, content, images_json),
        )


def get_messages(conversation_id):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT role, content, images_json FROM messages WHERE conversation_id = ? ORDER BY id",
            (conversation_id,),
        ).fetchall()

    messages = []
    for row in rows:
        item = dict(row)
        raw_images = item.pop("images_json", "[]")
        try:
            images = json.loads(raw_images or "[]")
        except (TypeError, json.JSONDecodeError):
            images = []
        item["images"] = images if isinstance(images, list) else []
        messages.append(item)

    return messages


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



def get_messages_with_ids(conversation_id):
    """Return complete stored conversation messages with stable database IDs."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, role, content, images_json, created_at
            FROM messages
            WHERE conversation_id = ?
            ORDER BY id
            """,
            (conversation_id,),
        ).fetchall()

    messages = []
    for row in rows:
        item = dict(row)
        raw_images = item.pop("images_json", "[]")
        try:
            images = json.loads(raw_images or "[]")
        except (TypeError, json.JSONDecodeError):
            images = []
        item["images"] = images if isinstance(images, list) else []
        messages.append(item)
    return messages


def get_conversation_summary(conversation_id):
    """Read the saved incremental summary state for one conversation."""
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT summary, summarized_through_message_id, updated_at
            FROM conversation_summaries
            WHERE conversation_id = ?
            """,
            (conversation_id,),
        ).fetchone()
    return dict(row) if row else None


def save_conversation_summary(
    conversation_id,
    summary,
    summarized_through_message_id,
):
    """Atomically replace summary text and advance its message cursor."""
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO conversation_summaries (
                conversation_id,
                summary,
                summarized_through_message_id,
                updated_at
            )
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(conversation_id) DO UPDATE SET
                summary = excluded.summary,
                summarized_through_message_id =
                    MAX(
                        conversation_summaries.summarized_through_message_id,
                        excluded.summarized_through_message_id
                    ),
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                conversation_id,
                str(summary or ""),
                int(summarized_through_message_id),
            ),
        )


def get_recent_images(conversation_id, limit=3):
    """Return the newest image attachments from a conversation, newest first."""
    max_images = max(0, min(int(limit), 3))
    if max_images == 0:
        return []

    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT images_json
            FROM messages
            WHERE conversation_id = ?
                AND images_json != '[]'
            ORDER BY id DESC
            """,
            (conversation_id,),
        ).fetchall()

    images = []
    for row in rows:
        try:
            stored = json.loads(row["images_json"] or "[]")
        except (TypeError, json.JSONDecodeError):
            continue

        if not isinstance(stored, list):
            continue

        for image in stored:
            if isinstance(image, dict) and isinstance(image.get("data"), str):
                images.append(image)
                if len(images) >= max_images:
                    return images

    return images
