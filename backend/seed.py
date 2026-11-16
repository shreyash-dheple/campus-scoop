"""Loads your real messes from messes.csv on every startup (adds only the missing ones).
Optional fake demo data: set the environment variable SAMPLE_DATA=1 (never needed for real use).
"""
import csv
import os
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from db import SESSION_KEYS, get_conn, init_db, make_nickname, today

CSV_PATH = Path(__file__).parent / "messes.csv"

DISHES = ["Dal", "Jeera rice", "Chapati", "Aloo gobi", "Paneer bhaji", "Poha", "Aloo paratha",
          "Misal", "Varan bhaat", "Bhendi fry", "Sev bhaji", "Curd", "Salad", "Kheer", "Pithla"]
COMMENTS = {
    "good": ["Roti was soft today", "Good food, worth the price", "Dal was tasty", "Fresh and hot"],
    "ok": ["Average, nothing special", "Okay for the price", "Fine but a bit bland"],
    "bad": ["Too oily today", "Long wait and cold food", "Not great, skip today"],
}


def load_messes_csv():
    if not CSV_PATH.exists():
        return
    with open(CSV_PATH, newline="", encoding="utf-8") as f, get_conn() as conn:
        for row in csv.DictReader(f):
            name = (row.get("name") or "").strip()
            area = (row.get("area") or "").strip()
            if name and not conn.execute("SELECT 1 FROM messes WHERE name = ?", (name,)).fetchone():
                conn.execute("INSERT INTO messes (name, area) VALUES (?, ?)", (name, area))


def add_sample_data():
    now = datetime.now(timezone.utc)
    with get_conn() as conn:
        if conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]:
            return
        for i, m in enumerate(conn.execute("SELECT id FROM messes").fetchall()):
            mess_id = m["id"]
            for sess in SESSION_KEYS:
                conn.execute(
                    "INSERT INTO menus (mess_id, day, session, items, nickname, token_hash, created_at) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (mess_id, today(), sess, ", ".join(random.sample(DISHES, 4)), make_nickname(),
                     f"seed-menu-{i}-{sess}", now.isoformat(timespec="seconds")))
            base = random.choice([2.8, 3.4, 3.8, 4.2])
            for k in range(random.randint(8, 14)):
                rating = max(1, min(5, round(random.gauss(base, 0.9))))
                kind = "good" if rating >= 4 else "ok" if rating == 3 else "bad"
                when = now - timedelta(days=random.randint(0, 6), hours=random.randint(0, 20))
                cur = conn.execute(
                    "INSERT OR IGNORE INTO reviews (mess_id, day, session, rating, comment, nickname, token_hash, created_at) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (mess_id, when.date().isoformat(), random.choice(SESSION_KEYS), rating, random.choice(COMMENTS[kind]),
                     make_nickname(), f"seed-{i}-{k}", when.isoformat(timespec="seconds")))
                if cur.lastrowid:
                    for v in range(random.randint(0, 6)):
                        conn.execute("INSERT OR IGNORE INTO votes (review_id, token_hash) VALUES (?, ?)",
                                     (cur.lastrowid, f"seed-voter-{v}"))


def seed_if_empty():  # name kept so main.py needs no change
    init_db()
    load_messes_csv()
    if os.getenv("SAMPLE_DATA") == "1":
        add_sample_data()


if __name__ == "__main__":
    seed_if_empty()
    print("Done.")