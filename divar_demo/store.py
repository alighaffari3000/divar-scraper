"""ذخیره‌سازی: کش جزئیات + تاریخچه قیمت.

SQLite با کتابخانه استاندارد. هیچ ویژگی خاص SQLite استفاده نشده تا مهاجرت به
PostgreSQL فقط تعویض connection باشد.
"""

import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

DEFAULT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "divar.db")

DETAIL_TTL_DAYS = 7  # متراژ و سال ساخت عوض نمی‌شوند؛ قیمت از لیست می‌آید

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    token       TEXT PRIMARY KEY,
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    lat         REAL,
    lon         REAL,
    detail_json TEXT,
    detail_at   TEXT
);
CREATE TABLE IF NOT EXISTS snapshots (
    token        TEXT NOT NULL,
    seen_at      TEXT NOT NULL,
    deposit      REAL,
    monthly_rent REAL,
    size         REAL,
    rooms        REAL,
    district     TEXT,
    title        TEXT,
    source       TEXT,
    PRIMARY KEY (token, seen_at)
);
CREATE TABLE IF NOT EXISTS searches (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,
    params_json    TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    last_run_at    TEXT,
    notify_chat_id TEXT
);
CREATE TABLE IF NOT EXISTS marks (
    token    TEXT NOT NULL,
    kind     TEXT NOT NULL,      -- 'trash' یا 'bookmark'
    marked_at TEXT NOT NULL,
    note     TEXT,
    PRIMARY KEY (token, kind)
);
CREATE INDEX IF NOT EXISTS idx_snapshots_token ON snapshots(token);
CREATE INDEX IF NOT EXISTS idx_marks_kind ON marks(kind);
"""


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    """اتصال بین نخ‌ها به اشتراک گذاشته می‌شود، پس هر دسترسی پشت یک قفل است."""

    def __init__(self, path=DEFAULT_PATH):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        with self.lock:
            self.conn.executescript(SCHEMA)
            self.conn.commit()

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # --- کش جزئیات ---

    def get_detail(self, token, ttl_days=DETAIL_TTL_DAYS):
        with self.lock:
            row = self.conn.execute(
                "SELECT detail_json, detail_at FROM posts WHERE token = ?", (token,)).fetchone()
        if not row or not row["detail_json"]:
            return None
        fresh_after = datetime.now(timezone.utc) - timedelta(days=ttl_days)
        if datetime.fromisoformat(row["detail_at"]) < fresh_after:
            return None
        return json.loads(row["detail_json"])

    def put_detail(self, token, detail):
        stamp = now()
        with self.lock:
            self.conn.execute(
                """INSERT INTO posts (token, first_seen, last_seen, detail_json, detail_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(token) DO UPDATE SET
                       detail_json = excluded.detail_json,
                       detail_at   = excluded.detail_at,
                       last_seen   = excluded.last_seen""",
                (token, stamp, stamp, json.dumps(detail, ensure_ascii=False), stamp))
            self.conn.commit()

    # --- تاریخچه ---

    def record(self, items, source="map"):
        """یک عکس لحظه‌ای از نتایج. بازگشت: مجموعه توکن‌هایی که اولین بار دیده شدند."""
        stamp = now()
        new_tokens = set()

        with self.lock:
            for item in items:
                token = item.get("token")
                if not token:
                    continue
                row = self.conn.execute(
                    "SELECT token FROM posts WHERE token = ?", (token,)).fetchone()
                if row is None:
                    new_tokens.add(token)
                self.conn.execute(
                    """INSERT INTO posts (token, first_seen, last_seen, lat, lon)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(token) DO UPDATE SET
                           last_seen = excluded.last_seen,
                           lat = COALESCE(excluded.lat, posts.lat),
                           lon = COALESCE(excluded.lon, posts.lon)""",
                    (token, stamp, stamp, item.get("lat"), item.get("lon")))
                self.conn.execute(
                    """INSERT OR REPLACE INTO snapshots
                       (token, seen_at, deposit, monthly_rent, size, rooms, district,
                        title, source)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (token, stamp, item.get("deposit"), item.get("monthly_rent"),
                     item.get("size"), item.get("rooms"), item.get("district"),
                     item.get("title"), source))

            self.conn.commit()
        return new_tokens

    def first_snapshot(self, token):
        with self.lock:
            return self.conn.execute(
                """SELECT deposit, monthly_rent, seen_at FROM snapshots
                   WHERE token = ? ORDER BY seen_at ASC LIMIT 1""", (token,)).fetchone()

    def annotate_history(self, items, new_tokens, rate):
        """به هر آگهی دو فیلد اضافه می‌کند: is_new و price_change_pct."""
        from .listing import full_rent_equivalent

        for item in items:
            token = item.get("token")
            item["is_new"] = token in new_tokens
            item["price_change_pct"] = None

            first = self.first_snapshot(token)
            if not first or item.get("full_rent_equivalent") is None:
                continue
            was = full_rent_equivalent(first["deposit"], first["monthly_rent"], rate)
            if was:
                item["price_change_pct"] = (item["full_rent_equivalent"] - was) / was * 100
                item["first_seen_at"] = first["seen_at"]
        return items

    # --- سطل آشغال و بوکمارک ---

    def mark(self, token, kind, note=None):
        """آگهی را در سطل آشغال یا بوکمارک بگذار."""
        with self.lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO marks (token, kind, marked_at, note) "
                "VALUES (?, ?, ?, ?)", (token, kind, now(), note))
            self.conn.commit()

    def unmark(self, token, kind):
        """بازگرداندن از سطل آشغال، یا حذف بوکمارک."""
        with self.lock:
            self.conn.execute("DELETE FROM marks WHERE token = ? AND kind = ?",
                              (token, kind))
            self.conn.commit()

    def marked_tokens(self, kind):
        with self.lock:
            return {r["token"] for r in
                    self.conn.execute("SELECT token FROM marks WHERE kind = ?", (kind,))}

    def marked_items(self, kind):
        """آگهی‌های علامت‌خورده با آخرین عکس لحظه‌ای‌شان — برای تب‌های پنل."""
        with self.lock:
            rows = self.conn.execute("""
                SELECT m.token, m.marked_at, m.note,
                       s.title, s.district, s.deposit, s.monthly_rent, s.size, s.rooms,
                       p.lat, p.lon, p.first_seen, p.last_seen
                FROM marks m
                LEFT JOIN posts p ON p.token = m.token
                LEFT JOIN snapshots s ON s.token = m.token
                     AND s.seen_at = (SELECT MAX(seen_at) FROM snapshots
                                      WHERE token = m.token)
                WHERE m.kind = ?
                ORDER BY m.marked_at DESC""", (kind,)).fetchall()
        return [dict(r) for r in rows]

    # --- جستجوهای ذخیره‌شده ---

    def save_search(self, name, params):
        with self.lock:
            cur = self.conn.execute(
                "INSERT INTO searches (name, params_json, created_at) VALUES (?, ?, ?)",
                (name, json.dumps(params, ensure_ascii=False), now()))
            self.conn.commit()
            return cur.lastrowid

    def list_searches(self):
        with self.lock:
            return [dict(r) for r in
                    self.conn.execute("SELECT * FROM searches ORDER BY created_at DESC")]

    def mark_search_run(self, search_id):
        with self.lock:
            self.conn.execute("UPDATE searches SET last_run_at = ? WHERE id = ?",
                              (now(), search_id))
            self.conn.commit()

    def delete_search(self, search_id):
        with self.lock:
            self.conn.execute("DELETE FROM searches WHERE id = ?", (search_id,))
            self.conn.commit()
