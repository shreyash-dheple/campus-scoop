import hashlib
import os
import secrets
import sqlite3
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from db import (DEMO_MODE, SESSION_KEYS, clock_info, default_session, fmt_time, get_conn, live_session,
                make_nickname, now_iso, session_info, session_status, today, week_start)
from seed import seed_if_empty

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
YEAR = 60 * 60 * 24 * 365
ADMIN_KEY = os.getenv("ADMIN_KEY", "scoop-admin")  # set ADMIN_KEY on Render before sharing the link

app = FastAPI(title="CampusScoop")


@app.on_event("startup")
def startup():
    seed_if_empty()


# ---------- anonymous device identity ----------
class Device:
    def __init__(self, token_hash: str, nickname: str):
        self.token_hash = token_hash
        self.nickname = nickname


def get_device(request: Request, response: Response) -> Device:
    """Random token in a cookie. Only its SHA-256 hash is ever stored."""
    token = request.cookies.get("cs_token")
    nickname = request.cookies.get("cs_nick")
    if not token:
        token = secrets.token_urlsafe(24)
        response.set_cookie("cs_token", token, max_age=YEAR, httponly=True, samesite="lax")
    if not nickname:
        nickname = make_nickname()
        response.set_cookie("cs_nick", nickname, max_age=YEAR, samesite="lax")
    return Device(hashlib.sha256(token.encode()).hexdigest(), nickname)


# ---------- request models ----------
class MenuIn(BaseModel):
    items: str = Field(max_length=300)
    session: str


class ReviewIn(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str = Field(default="", max_length=300)
    session: str


def valid_session(key: str) -> str:
    if key not in SESSION_KEYS:
        raise HTTPException(400, "Unknown session")
    return key


def ensure_open(key: str):
    """Posting is only allowed while the session is live (unless DEMO_MODE=1)."""
    if DEMO_MODE:
        return
    info = session_info(key)
    status = session_status(key)
    if status == "ended":
        raise HTTPException(400, f"The {info['name'].lower()} session has ended. Posting is closed.")
    if status == "upcoming":
        raise HTTPException(400, f"The {info['name'].lower()} session starts at {fmt_time(info['start'])}. Posting opens then.")


def require_mess(conn, mess_id: int):
    row = conn.execute("SELECT * FROM messes WHERE id = ?", (mess_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Mess not found")
    return row


# ---------- routes ----------
@app.get("/api/now")
def now():
    return clock_info()


@app.get("/api/messes")
def list_messes(device: Device = Depends(get_device)):
    live = live_session()
    info = session_info(live) if live else None
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT m.id, m.name, m.area,
                   COALESCE(AVG(r.rating), 0) AS avg_rating,
                   COUNT(r.id) AS review_count,
                   EXISTS (SELECT 1 FROM menus mn WHERE mn.mess_id = m.id AND mn.day = ? AND mn.session = ?) AS menu_now
            FROM messes m LEFT JOIN reviews r ON r.mess_id = m.id
            GROUP BY m.id ORDER BY avg_rating DESC, review_count DESC
            """, (today(), live or "")).fetchall()
    return [{**dict(r), "avg_rating": round(r["avg_rating"], 2), "menu_now": bool(r["menu_now"]),
             "session_name": info["name"] if info else None} for r in rows]


@app.get("/api/messes/{mess_id}")
def get_mess(mess_id: int, session: Optional[str] = None, device: Device = Depends(get_device)):
    sel = valid_session(session) if session else default_session()
    with get_conn() as conn:
        mess = require_mess(conn, mess_id)
        stats = conn.execute(
            "SELECT COALESCE(AVG(rating), 0) AS avg, COUNT(*) AS n FROM reviews WHERE mess_id = ?",
            (mess_id,)).fetchone()
        have = {r["session"] for r in conn.execute(
            "SELECT DISTINCT session FROM menus WHERE mess_id = ? AND day = ?", (mess_id, today()))}
        menu = conn.execute(
            "SELECT id, items, nickname, (token_hash = ?) AS mine FROM menus "
            "WHERE mess_id = ? AND day = ? AND session = ? ORDER BY id DESC LIMIT 1",
            (device.token_hash, mess_id, today(), sel)).fetchone()
        reviews = conn.execute(
            """
            SELECT r.id, r.rating, r.comment, r.nickname, r.day,
                   (SELECT COUNT(*) FROM votes v WHERE v.review_id = r.id) AS votes,
                   EXISTS (SELECT 1 FROM votes v WHERE v.review_id = r.id AND v.token_hash = ?) AS voted,
                   (r.token_hash = ?) AS mine
            FROM reviews r WHERE r.mess_id = ? AND r.session = ? AND r.day >= ?
            ORDER BY votes DESC, r.created_at DESC LIMIT 50
            """, (device.token_hash, device.token_hash, mess_id, sel, week_start())).fetchall()
    ratings = [r["rating"] for r in reviews]
    return {
        "id": mess["id"], "name": mess["name"], "area": mess["area"],
        "avg_rating": round(stats["avg"], 2), "review_count": stats["n"],
        "session": sel, "today": today(),
        "session_avg": round(sum(ratings) / len(ratings), 2) if ratings else 0,
        **clock_info(),
        "sessions": [{**x, "has_menu": x["key"] in have} for x in clock_info()["sessions"]],
        "menu": {**dict(menu), "mine": bool(menu["mine"])} if menu else None,
        "reviews": [{**dict(r), "voted": bool(r["voted"]), "mine": bool(r["mine"])} for r in reviews],
    }


@app.post("/api/messes/{mess_id}/menu")
def post_menu(mess_id: int, body: MenuIn, device: Device = Depends(get_device)):
    sess = valid_session(body.session)
    ensure_open(sess)
    items = body.items.strip()
    if not items:
        raise HTTPException(400, "Type what is being served first")
    with get_conn() as conn:
        require_mess(conn, mess_id)
        posted = conn.execute(
            "SELECT COUNT(*) FROM menus WHERE mess_id = ? AND day = ? AND session = ? AND token_hash = ?",
            (mess_id, today(), sess, device.token_hash)).fetchone()[0]
        if posted >= 3:
            raise HTTPException(400, "You've posted enough menus for this session")
        conn.execute(
            "INSERT INTO menus (mess_id, day, session, items, nickname, token_hash, created_at) VALUES (?,?,?,?,?,?,?)",
            (mess_id, today(), sess, items, device.nickname, device.token_hash, now_iso()))
    return {"ok": True}


@app.post("/api/messes/{mess_id}/reviews")
def post_review(mess_id: int, body: ReviewIn, device: Device = Depends(get_device)):
    sess = valid_session(body.session)
    ensure_open(sess)
    with get_conn() as conn:
        require_mess(conn, mess_id)
        try:
            conn.execute(
                "INSERT INTO reviews (mess_id, day, session, rating, comment, nickname, token_hash, created_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (mess_id, today(), sess, body.rating, body.comment.strip(), device.nickname,
                 device.token_hash, now_iso()))
        except sqlite3.IntegrityError:
            raise HTTPException(400, "You've already reviewed this session today")
    return {"ok": True}


@app.post("/api/reviews/{review_id}/vote")
def vote(review_id: int, device: Device = Depends(get_device)):
    with get_conn() as conn:
        review = conn.execute("SELECT token_hash FROM reviews WHERE id = ?", (review_id,)).fetchone()
        if not review:
            raise HTTPException(404, "Review not found")
        if review["token_hash"] == device.token_hash:
            raise HTTPException(400, "You can't vote on your own review")
        try:
            conn.execute("INSERT INTO votes (review_id, token_hash) VALUES (?, ?)",
                         (review_id, device.token_hash))
        except sqlite3.IntegrityError:
            raise HTTPException(400, "You've already voted on this review")
    return {"ok": True}


@app.delete("/api/reviews/{review_id}")
def delete_review(review_id: int, device: Device = Depends(get_device)):
    with get_conn() as conn:
        review = conn.execute("SELECT token_hash FROM reviews WHERE id = ?", (review_id,)).fetchone()
        if not review:
            raise HTTPException(404, "Review not found")
        if review["token_hash"] != device.token_hash:
            raise HTTPException(403, "You can only delete your own review")
        conn.execute("DELETE FROM votes WHERE review_id = ?", (review_id,))
        conn.execute("DELETE FROM reviews WHERE id = ?", (review_id,))
    return {"ok": True}


@app.delete("/api/menus/{menu_id}")
def delete_menu(menu_id: int, device: Device = Depends(get_device)):
    with get_conn() as conn:
        menu = conn.execute("SELECT token_hash FROM menus WHERE id = ?", (menu_id,)).fetchone()
        if not menu:
            raise HTTPException(404, "Menu not found")
        if menu["token_hash"] != device.token_hash:
            raise HTTPException(403, "You can only delete your own menu")
        conn.execute("DELETE FROM menus WHERE id = ?", (menu_id,))
    return {"ok": True}


# ---------- admin: add / remove messes (needs the admin key) ----------
class MessIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    area: str = Field(default="", max_length=80)


def check_admin(key: str):
    if not secrets.compare_digest(key.encode(), ADMIN_KEY.encode()):
        raise HTTPException(403, "Wrong admin key")


@app.post("/api/admin/messes")
def add_mess(body: MessIn, x_admin_key: str = Header(default="")):
    check_admin(x_admin_key)
    with get_conn() as conn:
        if conn.execute("SELECT 1 FROM messes WHERE name = ?", (body.name.strip(),)).fetchone():
            raise HTTPException(400, "A mess with this name already exists")
        conn.execute("INSERT INTO messes (name, area) VALUES (?, ?)", (body.name.strip(), body.area.strip()))
    return {"ok": True}


@app.delete("/api/admin/messes/{mess_id}")
def delete_mess(mess_id: int, x_admin_key: str = Header(default="")):
    check_admin(x_admin_key)
    with get_conn() as conn:
        require_mess(conn, mess_id)
        conn.execute("DELETE FROM votes WHERE review_id IN (SELECT id FROM reviews WHERE mess_id = ?)", (mess_id,))
        conn.execute("DELETE FROM reviews WHERE mess_id = ?", (mess_id,))
        conn.execute("DELETE FROM menus WHERE mess_id = ?", (mess_id,))
        conn.execute("DELETE FROM messes WHERE id = ?", (mess_id,))
    return {"ok": True}


@app.post("/api/admin/messes/{mess_id}/clear")
def clear_mess(mess_id: int, x_admin_key: str = Header(default="")):
    """Removes all reviews, votes and menus of one mess (reset before a demo)."""
    check_admin(x_admin_key)
    with get_conn() as conn:
        require_mess(conn, mess_id)
        conn.execute("DELETE FROM votes WHERE review_id IN (SELECT id FROM reviews WHERE mess_id = ?)", (mess_id,))
        conn.execute("DELETE FROM reviews WHERE mess_id = ?", (mess_id,))
        conn.execute("DELETE FROM menus WHERE mess_id = ?", (mess_id,))
    return {"ok": True}


@app.get("/")
def home():
    return RedirectResponse("/static/index.html")


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")