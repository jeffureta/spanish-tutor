import unittest
import os
import tempfile
import json
import sqlite3
import tutor_db


class TestTutorDB(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_state.db")
        tutor_db.DB_DIR = self.temp_dir.name
        tutor_db.DB_PATH = self.db_path
        tutor_db.init_db()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_init_and_profile(self):
        conn = tutor_db.get_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM user_profile WHERE id = 1")
        row = cur.fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row["cefr_level"], "UNASSESSED")

    def test_update_profile(self):
        tutor_db.update_profile("A2", "Travel & Dining", 50)
        conn = tutor_db.get_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM user_profile WHERE id = 1")
        row = cur.fetchone()
        conn.close()
        self.assertEqual(row["cefr_level"], "A2")
        self.assertEqual(row["target_focus"], "Travel & Dining")
        self.assertEqual(row["total_xp"], 50)

    def test_sm2_algorithm(self):
        # First successful review (q=4)
        rep, ef, interval = tutor_db.sm2_algorithm(4, 0, 2.5, 0)
        self.assertEqual(rep, 1)
        self.assertEqual(interval, 1)

        # Second successful review (q=5)
        rep, ef, interval = tutor_db.sm2_algorithm(5, rep, ef, interval)
        self.assertEqual(rep, 2)
        self.assertEqual(interval, 6)

        # Failed review (q=2) resets reps and interval
        rep, ef, interval = tutor_db.sm2_algorithm(2, rep, ef, interval)
        self.assertEqual(rep, 0)
        self.assertEqual(interval, 1)

    def test_vocab_lifecycle(self):
        tutor_db.add_vocab("hola", "hello", "greetings")
        conn = tutor_db.get_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM vocabulary WHERE spanish = 'hola'")
        row = cur.fetchone()
        vocab_id = row["id"]
        conn.close()

        self.assertEqual(row["repetition_count"], 0)

        # Review with quality 5
        tutor_db.record_review(vocab_id, 5, "hola", "Perfect!")
        conn = tutor_db.get_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM vocabulary WHERE id = ?", (vocab_id,))
        updated = cur.fetchone()
        conn.close()

        self.assertEqual(updated["repetition_count"], 1)
        self.assertEqual(updated["interval_days"], 1)

    def test_settings_and_session_summary(self):
        # Default settings check
        settings = tutor_db.get_settings(print_output=False)
        self.assertEqual(settings["feedback_style"], "balanced")
        self.assertEqual(settings["language_ratio"], "en_first")
        self.assertEqual(settings["current_mode"], "diagnostic")
        self.assertIsNone(settings["active_scenario"])
        self.assertEqual(settings["session_step"], 0)

        # Update setting
        res = tutor_db.set_setting("feedback_style", "strict", print_output=False)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["feedback_style"], "strict")

        # Session summary check
        summary = tutor_db.get_session_summary(print_output=False)
        self.assertEqual(summary["cefr_level"], "UNASSESSED")
        self.assertEqual(summary["feedback_style"], "strict")
        self.assertEqual(summary["due_vocab_count"], 0)

    def test_schema_migration_preserves_data(self):
        # Simulate an older db without new columns
        old_dir = tempfile.TemporaryDirectory()
        old_db_path = os.path.join(old_dir.name, "old.db")
        conn = sqlite3.connect(old_db_path)
        cur = conn.cursor()
        cur.execute("""
        CREATE TABLE user_profile (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            cefr_level TEXT DEFAULT 'UNASSESSED',
            diagnostic_completed_at TEXT,
            target_focus TEXT DEFAULT 'General Conversational',
            total_xp INTEGER DEFAULT 150,
            updated_at TEXT
        );
        """)
        cur.execute("INSERT INTO user_profile (id, cefr_level, total_xp) VALUES (1, 'B1', 150)")
        conn.commit()
        conn.close()

        # Run init_db on this db
        tutor_db.DB_DIR = old_dir.name
        tutor_db.DB_PATH = old_db_path
        tutor_db.init_db()

        # Check that data was preserved and columns added
        conn = tutor_db.get_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM user_profile WHERE id = 1")
        row = cur.fetchone()
        conn.close()
        old_dir.cleanup()

        self.assertEqual(row["cefr_level"], "B1")
        self.assertEqual(row["total_xp"], 150)
        self.assertEqual(row["feedback_style"], "balanced")

    def test_batch_sync(self):
        # Add vocab items
        tutor_db.add_vocab("manzana", "apple", "food")
        tutor_db.add_vocab("leche", "milk", "food")

        payload = {
            "reviews": [
                {"vocab_id": 1, "quality_score": 5, "user_response": "manzana", "feedback": "Perfect"},
                {"vocab_id": 2, "quality_score": 4, "user_response": "leche", "feedback": "Good"}
            ],
            "settings": {
                "feedback_style": "strict",
                "session_step": 4
            },
            "xp": 35,
            "mission": {
                "title": "Mercado Local",
                "cefr_level": "A1",
                "scenario_description": "Buying fruit and milk",
                "score": 95,
                "notes": "Excellent performance"
            }
        }

        res = tutor_db.batch_sync(payload, print_output=False)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["processed_reviews_count"], 2)
        self.assertEqual(res["processed_settings"]["feedback_style"], "strict")
        self.assertEqual(res["processed_settings"]["session_step"], 4)
        self.assertEqual(res["total_xp"], 35)
        self.assertIsNotNone(res["logged_mission"])
        self.assertEqual(res["logged_mission"]["score"], 95)

        # Verify db state
        conn = tutor_db.get_connection()
        cur = conn.cursor()
        cur.execute("SELECT repetition_count, interval_days FROM vocabulary WHERE id = 1")
        v1 = cur.fetchone()
        self.assertEqual(v1["repetition_count"], 1)
        self.assertEqual(v1["interval_days"], 1)

        cur.execute("SELECT COUNT(*) as count FROM missions WHERE title = 'Mercado Local'")
        m_count = cur.fetchone()["count"]
        self.assertEqual(m_count, 1)
        conn.close()

    def test_batch_sync_with_new_vocab_and_spanish_key_reviews(self):
        payload = {
            "new_vocab": [
                {"spanish": "la toalla", "english": "the towel", "category": "hotel"},
                {"spanish": "el jabón", "english": "the soap", "category": "hotel"}
            ],
            "reviews": [
                {"spanish": "la toalla", "quality_score": 5, "user_response": "la toalla", "feedback": "Perfect"},
                {"spanish": "el jabón", "quality_score": 4, "user_response": "el jabon", "feedback": "Watch accent"}
            ],
            "xp": 20
        }
        res = tutor_db.batch_sync(payload, print_output=False)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["processed_new_vocab_count"], 2)
        self.assertEqual(res["processed_reviews_count"], 2)

        # Verify db state
        conn = tutor_db.get_connection()
        cur = conn.cursor()
        cur.execute("SELECT repetition_count, interval_days FROM vocabulary WHERE spanish = 'la toalla'")
        v = cur.fetchone()
        self.assertIsNotNone(v)
        self.assertEqual(v["repetition_count"], 1)
        self.assertEqual(v["interval_days"], 1)
        conn.close()

    def test_scaffolding_setting_and_summary(self):
        # Default should be moderate
        summary = tutor_db.get_session_summary(print_output=False)
        self.assertEqual(summary.get("scaffolding_level"), "moderate")

        # Set to none
        res = tutor_db.set_setting("scaffolding_level", "none", print_output=False)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["scaffolding_level"], "none")

        summary = tutor_db.get_session_summary(print_output=False)
        self.assertEqual(summary["scaffolding_level"], "none")

        # Invalid scaffolding level
        bad_res = tutor_db.set_setting("scaffolding_level", "invalid_level", print_output=False)
        self.assertEqual(bad_res["status"], "error")

    def test_titration_step_calculation(self):
        # Titration step down when scoring high
        # high -> moderate -> subtle -> none
        next_scaffold, next_ratio, changed = tutor_db.evaluate_titration_step(
            current_scaffold="high",
            current_ratio="en_first",
            recent_scores=[5, 5, 4]
        )
        self.assertTrue(changed)
        self.assertEqual(next_scaffold, "moderate")
        self.assertEqual(next_ratio, "en_first")

        # subtle -> none
        next_scaffold, next_ratio, changed = tutor_db.evaluate_titration_step(
            current_scaffold="subtle",
            current_ratio="en_first",
            recent_scores=[5, 4, 5]
        )
        self.assertTrue(changed)
        self.assertEqual(next_scaffold, "none")
        self.assertEqual(next_ratio, "en_first")

        # none with en_first -> advances language_ratio to bilingual
        next_scaffold, next_ratio, changed = tutor_db.evaluate_titration_step(
            current_scaffold="none",
            current_ratio="en_first",
            recent_scores=[5, 5, 5]
        )
        self.assertTrue(changed)
        self.assertEqual(next_scaffold, "none")
        self.assertEqual(next_ratio, "bilingual")

        # none with bilingual -> advances language_ratio to immersion
        next_scaffold, next_ratio, changed = tutor_db.evaluate_titration_step(
            current_scaffold="none",
            current_ratio="bilingual",
            recent_scores=[5, 5, 5]
        )
        self.assertTrue(changed)
        self.assertEqual(next_scaffold, "none")
        self.assertEqual(next_ratio, "immersion")

        # Low scores do not titrate down
        next_scaffold, next_ratio, changed = tutor_db.evaluate_titration_step(
            current_scaffold="moderate",
            current_ratio="en_first",
            recent_scores=[2, 3, 3]
        )
        self.assertFalse(changed)
        self.assertEqual(next_scaffold, "moderate")
        self.assertEqual(next_ratio, "en_first")


if __name__ == "__main__":
    unittest.main()
