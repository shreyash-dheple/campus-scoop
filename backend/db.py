import os
import random
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent / "campusscoop.db"
IST = timezone(timedelta(hours=5, minutes=30))

SCHEMA = """
CREATE TABLE IF NOT EXISTS messes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    area TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS menus (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mess_id INTEGER NOT NULL REFERENCES messes(id),
    day TEXT NOT NULL,
    session TEXT NOT NULL,
    items TEXT NOT NULL,
    nickname TEXT NOT NULL,
    token_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mess_id INTEGER NOT NULL REFERENCES messes(id),
    day TEXT NOT NULL,
    session TEXT NOT NULL,
    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment TEXT NOT NULL DEFAULT '',
    nickname TEXT NOT NULL,
    token_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (mess_id, token_hash, day, session)
);
CREATE TABLE IF NOT EXISTS votes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    review_id INTEGER NOT NULL REFERENCES reviews(id),
    token_hash TEXT NOT NULL,
    UNIQUE (review_id, token_hash)
);
"""

ADJECTIVES = ["Hungry", "Sleepy", "Spicy", "Crispy", "Happy", "Sneaky", "Chill", "Cheesy"]
ANIMALS = ["Panda", "Tiger", "Parrot", "Koala", "Otter", "Fox", "Peacock", "Camel"]


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def today():
    return datetime.now(IST).date().isoformat()


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def make_nickname():
    return f"{random.choice(ADJECTIVES)}{random.choice(ANIMALS)}{random.randint(10, 99)}"


# Meal sessions. start/end are minutes since midnight (IST). Edit this list to rename or retime sessions.
SESSIONS = [
    {"key": "morning", "name": "Morning", "hint": "Breakfast", "icon": "🌅", "start": 5 * 60, "end": 11 * 60},
    {"key": "afternoon", "name": "Afternoon", "hint": "Lunch", "icon": "☀️", "start": 11 * 60, "end": 16 * 60},
    {"key": "evening", "name": "Evening", "hint": "Dinner", "icon": "🌙", "start": 16 * 60, "end": 23 * 60},
]
SESSION_KEYS = [x["key"] for x in SESSIONS]
# DEMO_MODE=1 lets you post to any session at any time (for testing). Leave it off for the real demo.
DEMO_MODE = os.getenv("DEMO_MODE") == "1"


def minutes_now():
    n = datetime.now(IST)
    return n.hour * 60 + n.minute


def fmt_time(m):
    h, mi = divmod(m, 60)
    return f"{h % 12 or 12}:{mi:02d} {'AM' if h < 12 else 'PM'}"


def session_info(key):
    return next(x for x in SESSIONS if x["key"] == key)


def session_status(key, now=None):
    now = minutes_now() if now is None else now
    s = session_info(key)
    return "live" if s["start"] <= now < s["end"] else "ended" if now >= s["end"] else "upcoming"


def live_session():
    return next((x["key"] for x in SESSIONS if session_status(x["key"]) == "live"), None)


def default_session():
    """Live session if there is one, otherwise the next one, otherwise the last of the day."""
    live = live_session()
    if live:
        return live
    return next((x["key"] for x in SESSIONS if session_status(x["key"]) == "upcoming"), SESSIONS[-1]["key"])


def clock_info():
    return {
        "now_ts": int(time.time() * 1000),
        "demo": DEMO_MODE,
        "sessions": [{**x, "start_label": fmt_time(x["start"]), "end_label": fmt_time(x["end"])} for x in SESSIONS],
    }


def week_start():
    """First day of the 7-day window used for reviews."""
    return (datetime.now(IST).date() - timedelta(days=6)).isoformat()