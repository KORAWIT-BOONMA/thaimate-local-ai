import base64
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException
from pydantic import ValidationError

import db
from ai.assistant import limit_conversation_history
from ai.ollama_client import build_payload
from main import ChatRequest, ImageAttachment, Message, reject_gemini_images


def make_png_attachment() -> ImageAttachment:
    raw = b"\x89PNG\r\n\x1a\n" + (b"thai-mate-test-image" * 3)
    return ImageAttachment(
        mime_type="image/png",
        data=base64.b64encode(raw).decode("ascii"),
        name="test.png",
    )


class ImageRequestTests(unittest.TestCase):
    def test_valid_png_attachment_is_accepted(self):
        image = make_png_attachment()
        message = Message(role="user", content="ช่วยดูภาพนี้", images=[image])
        request = ChatRequest(messages=[message], model_provider="ollama")

        self.assertEqual(len(request.messages[0].images), 1)

    def test_mime_type_must_match_image_signature(self):
        invalid_data = base64.b64encode(b"not-a-png-image" * 4).decode("ascii")
        with self.assertRaises(ValidationError):
            ImageAttachment(mime_type="image/png", data=invalid_data)

    def test_only_user_messages_can_carry_images(self):
        with self.assertRaises(ValidationError):
            Message(role="assistant", content="ภาพนี้คือ...", images=[make_png_attachment()])

    def test_gemini_image_request_is_rejected_explicitly(self):
        request = ChatRequest(
            messages=[
                Message(role="user", content="อธิบายภาพ", images=[make_png_attachment()])
            ],
            model_provider="gemini",
            cloud_consent=True,
        )
        with self.assertRaises(HTTPException) as context:
            reject_gemini_images(request)
        self.assertEqual(context.exception.status_code, 400)


class OllamaVisionPayloadTests(unittest.TestCase):
    def test_image_attachment_is_converted_to_ollama_base64_array(self):
        image = make_png_attachment()
        payload = build_payload(
            [{
                "role": "user",
                "content": "อธิบายภาพ",
                "images": [image.model_dump()],
            }]
        )
        self.assertEqual(payload["messages"][0]["images"], [image.data])

    def test_empty_image_metadata_is_removed_from_payload(self):
        payload = build_payload([
            {"role": "user", "content": "สวัสดี", "images": []}
        ])
        self.assertNotIn("images", payload["messages"][0])


class ConversationImagePersistenceTests(unittest.TestCase):
    def test_old_database_migrates_and_persists_image_history(self):
        with tempfile.TemporaryDirectory() as directory:
            test_db = Path(directory) / "thaimate-test.db"

            # Simulate the schema used by existing ThaiMate installations.
            with sqlite3.connect(test_db) as connection:
                connection.executescript(
                    """
                    CREATE TABLE conversations (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        title TEXT NOT NULL DEFAULT 'บทสนทนาใหม่',
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        model_provider TEXT NOT NULL DEFAULT 'ollama'
                    );
                    CREATE TABLE messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        conversation_id INTEGER NOT NULL
                            REFERENCES conversations(id) ON DELETE CASCADE,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    );
                    """
                )

            previous_path = db.DB_PATH
            db.DB_PATH = test_db
            try:
                db.init_db()
                conversation_id = db.create_conversation("Image history test")
                image = make_png_attachment()
                db.add_message(
                    conversation_id,
                    "user",
                    "ช่วยดูภาพนี้",
                    images=[image.model_dump()],
                )

                messages = db.get_messages(conversation_id)
                self.assertEqual(len(messages), 1)
                self.assertEqual(messages[0]["images"][0]["name"], "test.png")
                self.assertEqual(messages[0]["images"][0]["data"], image.data)

                # Existing text-only messages remain compatible.
                db.add_message(conversation_id, "assistant", "เห็นภาพแล้วครับ")
                messages = db.get_messages(conversation_id)
                self.assertEqual(messages[1]["images"], [])
            finally:
                db.DB_PATH = previous_path


class ConversationHistoryTests(unittest.TestCase):
    def test_recent_image_is_preserved_in_model_context(self):
        image = make_png_attachment().model_dump()
        history = limit_conversation_history([
            {"role": "user", "content": "ดูภาพนี้", "images": [image]},
            {"role": "assistant", "content": "ภาพแสดงวงจร"},
            {"role": "user", "content": "อธิบายเพิ่ม"},
        ])
        self.assertEqual(history[0]["images"][0]["name"], "test.png")


if __name__ == "__main__":
    unittest.main()
