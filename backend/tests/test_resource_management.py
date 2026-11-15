import asyncio
import tempfile
import unittest
from pathlib import Path

import db
from ai.resource_manager import get_resource_snapshot, ollama_request
from ai.conversation_memory import _select_summary_batch


class ConversationSummarySelectionTests(unittest.TestCase):
    def test_only_old_complete_turns_are_selected(self):
        messages = []
        for index in range(1, 17):
            messages.append({
                "id": index,
                "role": "user" if index % 2 else "assistant",
                "content": f"message {index}",
                "images": [],
            })

        selected = _select_summary_batch(messages, 0)

        self.assertEqual([item["id"] for item in selected], list(range(1, 9)))
        self.assertEqual(selected[-1]["role"], "assistant")

    def test_incremental_cursor_excludes_already_summarized_messages(self):
        messages = [
            {
                "id": index,
                "role": "user" if index % 2 else "assistant",
                "content": f"message {index}",
                "images": [],
            }
            for index in range(1, 17)
        ]

        selected = _select_summary_batch(messages, 4)

        self.assertEqual([item["id"] for item in selected], [5, 6, 7, 8])


class ConversationSummaryDatabaseTests(unittest.TestCase):
    def test_summary_is_persisted_and_removed_with_conversation(self):
        with tempfile.TemporaryDirectory() as directory:
            previous_path = db.DB_PATH
            db.DB_PATH = Path(directory) / "summary-test.db"
            try:
                db.init_db()
                conversation_id = db.create_conversation("Summary test")
                db.add_message(conversation_id, "user", "สวัสดี")
                db.save_conversation_summary(conversation_id, "ผู้ใช้กำลังทดสอบ", 1)

                state = db.get_conversation_summary(conversation_id)
                self.assertEqual(state["summary"], "ผู้ใช้กำลังทดสอบ")
                self.assertEqual(state["summarized_through_message_id"], 1)

                db.delete_conversation(conversation_id)
                self.assertIsNone(db.get_conversation_summary(conversation_id))
            finally:
                db.DB_PATH = previous_path


class OllamaResourceQueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_ollama_calls_are_serialized(self):
        active = 0
        peak_active = 0

        async def simulated_request(name):
            nonlocal active, peak_active
            async with ollama_request(name):
                active += 1
                peak_active = max(peak_active, active)
                await asyncio.sleep(0.02)
                active -= 1

        await asyncio.gather(
            simulated_request("test-a"),
            simulated_request("test-b"),
            simulated_request("test-c"),
        )

        self.assertEqual(peak_active, 1)
        self.assertFalse(get_resource_snapshot()["is_busy"])
        self.assertEqual(get_resource_snapshot()["queued_requests"], 0)


if __name__ == "__main__":
    unittest.main()
