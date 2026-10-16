"""SQLite 存储：抓到的每条消息、分类结果、线索跟进状态、运行记录。"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,            -- telegram / news
    channel TEXT NOT NULL,           -- 频道名或新闻查询词
    ext_id TEXT NOT NULL,            -- 频道帖子号或新闻链接
    url TEXT,
    text TEXT NOT NULL,
    posted_at TEXT,
    fetched_at TEXT NOT NULL,
    category TEXT,                   -- lead / rate / competitor / policy / noise；NULL 表示还没分类
    score REAL,
    fields TEXT,                     -- 模型抽出的字段（JSON）
    status TEXT NOT NULL DEFAULT 'new',  -- new / contacted / quoted / won / lost / ignored
    note TEXT,
    reported_at TEXT,
    UNIQUE (source, ext_id)
);
CREATE INDEX IF NOT EXISTS idx_items_cat ON items (category, fetched_at);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,              -- collect / brief
    started_at TEXT NOT NULL,
    finished_at TEXT,
    ok INTEGER,
    summary TEXT
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""

STATUSES = ("new", "contacted", "quoted", "won", "lost", "ignored")
CATEGORIES = ("lead", "rate", "competitor", "policy", "noise")

_init_lock = threading.Lock()
_initialized: set[str] = set()


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def db_path() -> Path:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    return config.DATA_DIR / "radar.db"


@contextmanager
def connect():
    path = str(db_path())
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    with _init_lock:
        if path not in _initialized:
            conn.executescript(SCHEMA)
            _initialized.add(path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def insert_items(rows: list[dict]) -> int:
    """插入新消息，已存在的跳过。返回新增条数。"""
    added = 0
    with connect() as conn:
        for r in rows:
            cur = conn.execute(
                "INSERT OR IGNORE INTO items (source, channel, ext_id, url, text, posted_at, fetched_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (r["source"], r["channel"], r["ext_id"], r.get("url"), r["text"], r.get("posted_at"), now_iso()),
            )
            added += cur.rowcount
    return added


def unclassified(limit: int) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, source, channel, text FROM items WHERE category IS NULL ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def save_classification(item_id: int, category: str, score: float, fields: dict) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE items SET category = ?, score = ?, fields = ? WHERE id = ?",
            (category, score, json.dumps(fields, ensure_ascii=False), item_id),
        )


def mark_skipped(ids: list[int]) -> None:
    """超出单次上限、未分类的旧消息标成 noise，避免越积越多。"""
    if not ids:
        return
    with connect() as conn:
        conn.executemany("UPDATE items SET category = 'noise', score = 0 WHERE id = ?", [(i,) for i in ids])


def last_ext_id(source: str, channel: str) -> str | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT ext_id FROM items WHERE source = ? AND channel = ? ORDER BY CAST(ext_id AS INTEGER) DESC LIMIT 1",
            (source, channel),
        ).fetchone()
    return row["ext_id"] if row else None


def _row(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["fields"] = json.loads(d["fields"]) if d.get("fields") else {}
    return d


def query_items(
    category: str | None = None,
    status: str | None = None,
    days: float = 7,
    min_score: float = 0,
    limit: int = 50,
    text: str | None = None,
    unreported_only: bool = False,
) -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    sql = "SELECT * FROM items WHERE fetched_at >= ? AND COALESCE(score, 0) >= ?"
    args: list = [since, min_score]
    if category:
        sql += " AND category = ?"
        args.append(category)
    else:
        sql += " AND category IS NOT NULL AND category != 'noise'"
    if status:
        sql += " AND status = ?"
        args.append(status)
    if text:
        sql += " AND (text LIKE ? OR fields LIKE ?)"
        args += [f"%{text}%", f"%{text}%"]
    if unreported_only:
        sql += " AND reported_at IS NULL"
    sql += " ORDER BY score DESC, id DESC LIMIT ?"
    args.append(limit)
    with connect() as conn:
        return [_row(r) for r in conn.execute(sql, args).fetchall()]


def get_item(item_id: int) -> dict | None:
    with connect() as conn:
        r = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    return _row(r) if r else None


def update_status(item_id: int, status: str, note: str | None = None) -> bool:
    if status not in STATUSES:
        raise ValueError(f"状态只能是 {', '.join(STATUSES)}")
    with connect() as conn:
        if note is None:
            cur = conn.execute("UPDATE items SET status = ? WHERE id = ?", (status, item_id))
        else:
            cur = conn.execute("UPDATE items SET status = ?, note = ? WHERE id = ?", (status, note, item_id))
    return cur.rowcount > 0


def mark_reported(ids: list[int]) -> None:
    ts = now_iso()
    with connect() as conn:
        conn.executemany("UPDATE items SET reported_at = ? WHERE id = ?", [(ts, i) for i in ids])


def start_run(kind: str) -> int:
    with connect() as conn:
        return conn.execute("INSERT INTO runs (kind, started_at) VALUES (?, ?)", (kind, now_iso())).lastrowid


def finish_run(run_id: int, ok: bool, summary: str) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE runs SET finished_at = ?, ok = ?, summary = ? WHERE id = ?",
            (now_iso(), int(ok), summary, run_id),
        )


def recent_runs(limit: int = 10) -> list[dict]:
    with connect() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]


def get_meta(key: str) -> str | None:
    with connect() as conn:
        r = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return r["value"] if r else None


def set_meta(key: str, value: str) -> None:
    with connect() as conn:
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))


def source_stats(days: float = 30) -> list[dict]:
    """复盘：每个来源产出多少线索、跟进了多少、成了多少。"""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT source, channel,
                   COUNT(*) AS total,
                   SUM(category = 'lead') AS leads,
                   SUM(category IN ('rate', 'competitor', 'policy')) AS intel,
                   SUM(category = 'noise') AS noise,
                   SUM(status IN ('contacted', 'quoted', 'won', 'lost')) AS contacted,
                   SUM(status IN ('quoted', 'won', 'lost')) AS quoted,
                   SUM(status = 'won') AS won
            FROM items WHERE fetched_at >= ? AND category IS NOT NULL
            GROUP BY source, channel ORDER BY leads DESC, intel DESC
            """,
            (since,),
        ).fetchall()
    return [dict(r) for r in rows]
