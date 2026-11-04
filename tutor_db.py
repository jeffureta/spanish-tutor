#!/usr/bin/env python3
"""
tutor_db.py - SQLite persistence engine and CLI helper for Spanish Tutor.
Implements the SuperMemo SM-2 spaced repetition algorithm, profile tracking,
and mission logging.
"""

import sys
import os
import sqlite3
import json
from datetime import datetime, timezone, timedelta

DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".tutor")
DB_PATH = os.path.join(DB_DIR, "state.db")


def get_connection():
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(print_output=True):
    with get_connection() as conn:
        cursor = conn.cursor()

        # User Profile table with session settings
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_profile (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            cefr_level TEXT DEFAULT 'UNASSESSED',
            diagnostic_completed_at TEXT,
            target_focus TEXT DEFAULT 'General Conversational',
            total_xp INTEGER DEFAULT 0,
            feedback_style TEXT DEFAULT 'balanced',
            language_ratio TEXT DEFAULT 'en_first',
            current_mode TEXT DEFAULT 'diagnostic',
            active_scenario TEXT,
            session_step INTEGER DEFAULT 0,
            updated_at TEXT
        );
        """)

        # Lightweight migration for existing user_profile schemas
        cursor.execute("PRAGMA table_info(user_profile)")
        existing_cols = {row["name"] for row in cursor.fetchall()}
        migrations = [
            ("feedback_style", "TEXT DEFAULT 'balanced'"),
            ("language_ratio", "TEXT DEFAULT 'en_first'"),
            ("current_mode", "TEXT DEFAULT 'diagnostic'"),
            ("active_scenario", "TEXT"),
            ("session_step", "INTEGER DEFAULT 0"),
        ]
        for col_name, col_def in migrations:
            if col_name not in existing_cols:
                cursor.execute(f"ALTER TABLE user_profile ADD COLUMN {col_name} {col_def}")

        # Vocabulary & Phrase items for Spaced Repetition (SM-2)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS vocabulary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            spanish TEXT UNIQUE NOT NULL,
            english TEXT NOT NULL,
            category TEXT,
            repetition_count INTEGER DEFAULT 0,
            ease_factor REAL DEFAULT 2.5,
            interval_days INTEGER DEFAULT 0,
            next_review_at TEXT,
            last_reviewed_at TEXT,
            created_at TEXT
        );
        """)

        # Review logs
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS review_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vocab_id INTEGER,
            quality_score INTEGER,  -- 0 to 5 (SM-2 scale)
            user_response TEXT,
            feedback TEXT,
            reviewed_at TEXT,
            FOREIGN KEY(vocab_id) REFERENCES vocabulary(id)
        );
        """)

        # Mission / Scenario activity history
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS missions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            cefr_level TEXT,
            scenario_description TEXT,
            status TEXT DEFAULT 'COMPLETED', -- IN_PROGRESS, COMPLETED
            score INTEGER,                  -- 0 to 100
            notes TEXT,
            completed_at TEXT
        );
        """)

        # Performance indexes for fast querying and sorting
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_vocab_review ON vocabulary(next_review_at);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_missions_status ON missions(status);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_review_vocab_id ON review_log(vocab_id);")

        # Ensure profile row exists
        cursor.execute("SELECT id FROM user_profile WHERE id = 1")
        if not cursor.fetchone():
            now = datetime.now(timezone.utc).isoformat()
            cursor.execute("""
            INSERT INTO user_profile (id, cefr_level, diagnostic_completed_at, target_focus, total_xp, updated_at)
            VALUES (1, 'UNASSESSED', NULL, 'General Conversational', 0, ?)
            """, (now,))

        conn.commit()
    if print_output:
        print(json.dumps({"status": "success", "message": "Database initialized at " + DB_PATH}))


def get_profile(print_output=True):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM user_profile WHERE id = 1")
        row = cursor.fetchone()
    if row:
        data = dict(row)
        if print_output:
            print(json.dumps(data, indent=2))
        return data
    else:
        err = {"error": "Profile not found"}
        if print_output:
            print(json.dumps(err))
        return err


def get_settings(print_output=True):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        SELECT feedback_style, language_ratio, current_mode, active_scenario, session_step
        FROM user_profile WHERE id = 1
        """)
        row = cursor.fetchone()
    if row:
        data = dict(row)
        if print_output:
            print(json.dumps(data, indent=2))
        return data
    else:
        err = {"error": "Settings not found"}
        if print_output:
            print(json.dumps(err))
        return err


def set_setting(key, value, print_output=True):
    allowed_keys = {
        "feedback_style": str,
        "language_ratio": str,
        "current_mode": str,
        "active_scenario": str,
        "session_step": int,
        "cefr_level": str,
        "target_focus": str
    }
    if key not in allowed_keys:
        err = {"status": "error", "message": f"Invalid setting key: {key}. Allowed: {list(allowed_keys.keys())}"}
        if print_output:
            print(json.dumps(err))
        return err

    typed_value = allowed_keys[key](value) if value is not None else None
    now = datetime.now(timezone.utc).isoformat()

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(f"""
        UPDATE user_profile
        SET {key} = ?, updated_at = ?
        WHERE id = 1
        """, (typed_value, now))
        conn.commit()

    res = {"status": "success", "key": key, key: typed_value}
    if print_output:
        print(json.dumps(res, indent=2))
    return res


def get_session_summary(print_output=True):
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        cursor = conn.cursor()
        # Single coalesced query combining profile with aggregate metrics
        cursor.execute("""
        SELECT
            p.*,
            (SELECT COUNT(*) FROM vocabulary WHERE next_review_at IS NULL OR next_review_at <= ?) AS due_vocab_count,
            (SELECT COUNT(*) FROM vocabulary) AS total_vocab_count,
            (SELECT COUNT(*) FROM missions WHERE status = 'COMPLETED') AS completed_missions_count
        FROM user_profile p
        WHERE p.id = 1
        """, (now,))
        row = cursor.fetchone()

    summary = dict(row) if row else {
        "due_vocab_count": 0,
        "total_vocab_count": 0,
        "completed_missions_count": 0
    }

    if print_output:
        print(json.dumps(summary, indent=2))
    return summary


def update_profile(cefr_level, target_focus=None, add_xp=0, print_output=True):
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        UPDATE user_profile
        SET cefr_level = ?,
            diagnostic_completed_at = COALESCE(diagnostic_completed_at, ?),
            target_focus = COALESCE(?, target_focus),
            total_xp = total_xp + ?,
            updated_at = ?
        WHERE id = 1
        """, (cefr_level, now, target_focus, int(add_xp), now))

        cursor.execute("SELECT total_xp FROM user_profile WHERE id = 1")
        row = cursor.fetchone()
        new_xp = row["total_xp"] if row else 0
        conn.commit()

    res = {"status": "success", "cefr_level": cefr_level, "total_xp": new_xp}
    if print_output:
        print(json.dumps(res))
    return res


def add_vocab(spanish, english, category="general", print_output=True):
    now = datetime.now(timezone.utc).isoformat()
    clean_sp = spanish.strip()
    clean_en = english.strip()
    clean_cat = category.strip()
    with get_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("""
            INSERT INTO vocabulary (spanish, english, category, repetition_count, ease_factor, interval_days, next_review_at, last_reviewed_at, created_at)
            VALUES (?, ?, ?, 0, 2.5, 0, ?, NULL, ?)
            """, (clean_sp, clean_en, clean_cat, now, now))
            conn.commit()
            res = {"status": "success", "vocab_id": cursor.lastrowid, "spanish": clean_sp}
        except sqlite3.IntegrityError:
            res = {"status": "exists", "spanish": clean_sp}

    if print_output:
        print(json.dumps(res))
    return res


def get_due_vocab(limit=10, print_output=True):
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        SELECT * FROM vocabulary
        WHERE next_review_at IS NULL OR next_review_at <= ?
        ORDER BY next_review_at ASC
        LIMIT ?
        """, (now, int(limit)))
        rows = [dict(r) for r in cursor.fetchall()]

    if print_output:
        print(json.dumps(rows, indent=2))
    return rows


def sm2_algorithm(quality, repetition_count, ease_factor, interval_days):
    """
    Standard SuperMemo-2 (SM-2) algorithm.
    quality: int 0-5
    """
    if quality >= 3:
        if repetition_count == 0:
            interval = 1
        elif repetition_count == 1:
            interval = 6
        else:
            interval = int(round(interval_days * ease_factor))
        repetition_count += 1
    else:
        repetition_count = 0
        interval = 1

    # EF' = EF + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
    ease_factor = max(1.3, ease_factor + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)))
    return repetition_count, ease_factor, interval


def record_review(vocab_id, quality_score, user_response="", feedback="", print_output=True):
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat()

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT repetition_count, ease_factor, interval_days FROM vocabulary WHERE id = ?", (vocab_id,))
        vocab = cursor.fetchone()
        if not vocab:
            err = {"error": f"Vocab id {vocab_id} not found"}
            if print_output:
                print(json.dumps(err))
            return err

        quality = max(0, min(5, int(quality_score)))
        rep_count, ef, interval = sm2_algorithm(
            quality,
            vocab["repetition_count"],
            vocab["ease_factor"],
            vocab["interval_days"]
        )

        next_review = (now_dt + timedelta(days=interval)).isoformat()

        cursor.execute("""
        UPDATE vocabulary
        SET repetition_count = ?,
            ease_factor = ?,
            interval_days = ?,
            next_review_at = ?,
            last_reviewed_at = ?
        WHERE id = ?
        """, (rep_count, ef, interval, next_review, now, vocab_id))

        cursor.execute("""
        INSERT INTO review_log (vocab_id, quality_score, user_response, feedback, reviewed_at)
        VALUES (?, ?, ?, ?, ?)
        """, (vocab_id, quality, user_response, feedback, now))
        conn.commit()

    res = {
        "status": "success",
        "vocab_id": vocab_id,
        "quality": quality,
        "interval_days": interval,
        "next_review_at": next_review
    }
    if print_output:
        print(json.dumps(res))
    return res


def log_mission(title, cefr_level, scenario_description, score, notes="", print_output=True):
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO missions (title, cefr_level, scenario_description, status, score, notes, completed_at)
        VALUES (?, ?, ?, 'COMPLETED', ?, ?, ?)
        """, (title, cefr_level, scenario_description, int(score), notes, now))
        conn.commit()

    res = {"status": "success", "title": title, "score": score}
    if print_output:
        print(json.dumps(res))
    return res


def batch_sync(payload, print_output=True):
    """
    Executes multiple updates (reviews, settings, profile/xp, mission) in a single atomic transaction.
    Reduces agent subprocess calls from N calls to 1 call at milestone/conclusion steps.
    Payload format:
    {
        "new_vocab": [
            {"spanish": "la llave", "english": "the key", "category": "hotel"},
            ...
        ],
        "reviews": [
            {"vocab_id": 1, "quality_score": 5, "user_response": "...", "feedback": "..."},
            # Or identify review target by spanish word directly:
            {"spanish": "la llave", "quality_score": 5, "user_response": "la llave", "feedback": "Good"}
        ],
        "settings": {
            "session_step": 3,
            "feedback_style": "strict",
            ...
        },
        "xp": 50,
        "mission": {
            "title": "...",
            "cefr_level": "A2",
            "scenario_description": "...",
            "score": 90,
            "notes": "..."
        }
    }
    """
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat()
    processed_new_vocab = []
    processed_reviews = []
    processed_settings = {}
    logged_mission = None
    new_total_xp = None

    with get_connection() as conn:
        cursor = conn.cursor()

        # 1. Process new_vocab ingestion
        for item in payload.get("new_vocab", []):
            sp = item.get("spanish", "").strip()
            en = item.get("english", "").strip()
            cat = item.get("category", "general")
            if not sp or not en:
                continue
            cursor.execute("SELECT id FROM vocabulary WHERE spanish = ?", (sp,))
            existing = cursor.fetchone()
            if existing:
                vocab_id = existing["id"]
            else:
                cursor.execute("""
                INSERT INTO vocabulary (spanish, english, category, repetition_count, ease_factor, interval_days, next_review_at, created_at)
                VALUES (?, ?, ?, 0, 2.5, 0, ?, ?)
                """, (sp, en, cat, now, now))
                vocab_id = cursor.lastrowid

            processed_new_vocab.append({
                "vocab_id": vocab_id,
                "spanish": sp,
                "english": en,
                "category": cat
            })

        # 2. Process reviews (supports vocab_id or spanish word)
        for review in payload.get("reviews", []):
            vocab_id = review.get("vocab_id")
            sp_word = review.get("spanish")
            quality_score = review.get("quality_score", 3)
            user_response = review.get("user_response", "")
            feedback = review.get("feedback", "")

            if vocab_id is None and sp_word:
                cursor.execute("SELECT id, repetition_count, ease_factor, interval_days FROM vocabulary WHERE spanish = ?", (sp_word.strip(),))
                vocab = cursor.fetchone()
                if vocab:
                    vocab_id = vocab["id"]
            elif vocab_id is not None:
                cursor.execute("SELECT id, repetition_count, ease_factor, interval_days FROM vocabulary WHERE id = ?", (vocab_id,))
                vocab = cursor.fetchone()
            else:
                vocab = None

            if vocab and vocab_id is not None:
                quality = max(0, min(5, int(quality_score)))
                rep_count, ef, interval = sm2_algorithm(
                    quality,
                    vocab["repetition_count"],
                    vocab["ease_factor"],
                    vocab["interval_days"]
                )
                next_review = (now_dt + timedelta(days=interval)).isoformat()

                cursor.execute("""
                UPDATE vocabulary
                SET repetition_count = ?,
                    ease_factor = ?,
                    interval_days = ?,
                    next_review_at = ?,
                    last_reviewed_at = ?
                WHERE id = ?
                """, (rep_count, ef, interval, next_review, now, vocab_id))

                cursor.execute("""
                INSERT INTO review_log (vocab_id, quality_score, user_response, feedback, reviewed_at)
                VALUES (?, ?, ?, ?, ?)
                """, (vocab_id, quality, user_response, feedback, now))

                processed_reviews.append({
                    "vocab_id": vocab_id,
                    "quality": quality,
                    "interval_days": interval,
                    "next_review_at": next_review
                })

        # 2. Process settings
        settings_to_update = payload.get("settings", {})
        allowed_keys = {
            "feedback_style": str,
            "language_ratio": str,
            "current_mode": str,
            "active_scenario": str,
            "session_step": int,
            "cefr_level": str,
            "target_focus": str
        }
        for key, val in settings_to_update.items():
            if key in allowed_keys:
                typed_val = allowed_keys[key](val) if val is not None else None
                cursor.execute(f"UPDATE user_profile SET {key} = ?, updated_at = ? WHERE id = 1", (typed_val, now))
                processed_settings[key] = typed_val

        # 3. Add XP if specified
        add_xp = payload.get("xp", 0)
        if add_xp:
            cursor.execute("UPDATE user_profile SET total_xp = total_xp + ?, updated_at = ? WHERE id = 1", (int(add_xp), now))

        cursor.execute("SELECT total_xp FROM user_profile WHERE id = 1")
        row = cursor.fetchone()
        if row:
            new_total_xp = row["total_xp"]

        # 4. Process mission if specified
        mission = payload.get("mission")
        if mission:
            title = mission.get("title", "Untitled Mission")
            cefr_level = mission.get("cefr_level", "A1")
            desc = mission.get("scenario_description", "")
            score = int(mission.get("score", 100))
            notes = mission.get("notes", "")
            cursor.execute("""
            INSERT INTO missions (title, cefr_level, scenario_description, status, score, notes, completed_at)
            VALUES (?, ?, ?, 'COMPLETED', ?, ?, ?)
            """, (title, cefr_level, desc, score, notes, now))
            logged_mission = {"title": title, "score": score}

        conn.commit()

    result = {
        "status": "success",
        "processed_new_vocab_count": len(processed_new_vocab),
        "processed_new_vocab": processed_new_vocab,
        "processed_reviews_count": len(processed_reviews),
        "processed_reviews": processed_reviews,
        "processed_settings": processed_settings,
        "total_xp": new_total_xp,
        "logged_mission": logged_mission
    }
    if print_output:
        print(json.dumps(result, indent=2))
    return result


def main():
    if len(sys.argv) < 2:
        print("Usage: tutor_db.py <init|get-profile|update-profile|add-vocab|get-due-vocab|record-review|log-mission> [args...]")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "init":
        init_db()
    elif cmd == "get-profile":
        get_profile()
    elif cmd == "get-settings":
        get_settings()
    elif cmd == "set-setting":
        if len(sys.argv) < 4:
            print("Usage: tutor_db.py set-setting <key> <value>")
            sys.exit(1)
        key = sys.argv[2]
        value = sys.argv[3]
        set_setting(key, value)
    elif cmd == "get-session-summary":
        get_session_summary()
    elif cmd == "update-profile":
        # update-profile <cefr_level> [target_focus] [add_xp]
        level = sys.argv[2]
        focus = sys.argv[3] if len(sys.argv) > 3 else None
        xp = int(sys.argv[4]) if len(sys.argv) > 4 else 0
        update_profile(level, focus, xp)
    elif cmd == "add-vocab":
        # add-vocab <spanish> <english> [category]
        spanish = sys.argv[2]
        english = sys.argv[3]
        category = sys.argv[4] if len(sys.argv) > 4 else "general"
        add_vocab(spanish, english, category)
    elif cmd == "get-due-vocab":
        limit = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        get_due_vocab(limit)
    elif cmd == "record-review":
        # record-review <vocab_id> <quality_0_5> [user_response] [feedback]
        vocab_id = int(sys.argv[2])
        quality = int(sys.argv[3])
        response = sys.argv[4] if len(sys.argv) > 4 else ""
        feedback = sys.argv[5] if len(sys.argv) > 5 else ""
        record_review(vocab_id, quality, response, feedback)
    elif cmd == "log-mission":
        # log-mission <title> <cefr_level> <scenario_desc> <score> [notes]
        title = sys.argv[2]
        level = sys.argv[3]
        desc = sys.argv[4]
        score = int(sys.argv[5])
        notes = sys.argv[6] if len(sys.argv) > 6 else ""
        log_mission(title, level, desc, score, notes)
    elif cmd == "batch-sync":
        # batch-sync <json_payload_or_stdin>
        # payload structure: {"reviews": [...], "settings": {...}, "mission": {...}, "xp": int}
        if len(sys.argv) > 2:
            raw_input = sys.argv[2]
        else:
            raw_input = sys.stdin.read()
        try:
            payload = json.loads(raw_input)
            results = batch_sync(payload)
        except Exception as e:
            results = {"status": "error", "message": f"Failed to parse payload: {str(e)}"}
            print(json.dumps(results))
            sys.exit(1)
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
