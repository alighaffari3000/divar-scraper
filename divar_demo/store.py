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
    notify_chat_id TEXT,
    enabled        INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS marks (
    token    TEXT NOT NULL,
    kind     TEXT NOT NULL,      -- 'trash' یا 'bookmark'
    marked_at TEXT NOT NULL,
    note     TEXT,
    PRIMARY KEY (token, kind)
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS sent_posts (      -- آنچه بات در گروه پست کرده
    token      TEXT NOT NULL,
    chat_id    TEXT NOT NULL,
    message_id INTEGER,
    search_id  INTEGER,
    sent_at    TEXT NOT NULL,
    score      REAL,
    last_fre   REAL,                          -- آخرین رهن معادلی که اطلاع داده شد
    media_ids  TEXT,                          -- شناسه پیام‌های گالری، برای حذف دسته‌جمعی
    PRIMARY KEY (token, chat_id)
);
CREATE TABLE IF NOT EXISTS bot_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    ok          INTEGER,
    error       TEXT,
    sent        INTEGER DEFAULT 0
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
            # دو فرایند (پنل و بات) هم‌زمان می‌نویسند؛ WAL نمی‌گذارد همدیگر را بلاک کنند
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA busy_timeout=5000")
            self.conn.executescript(SCHEMA)
            # دیتابیس‌هایی که قبل از افزوده‌شدن enabled ساخته شده‌اند
            for table, column, ddl in (
                ("searches", "enabled", "ALTER TABLE searches ADD COLUMN "
                                        "enabled INTEGER NOT NULL DEFAULT 1"),
                ("sent_posts", "media_ids", "ALTER TABLE sent_posts ADD COLUMN media_ids TEXT"),
            ):
                cols = {r["name"] for r in self.conn.execute(f"PRAGMA table_info({table})")}
                if column in cols:
                    continue
                try:
                    self.conn.execute(ddl)
                except sqlite3.OperationalError:
                    pass  # اتصال دیگری (پنل یا بات) هم‌زمان همین را اضافه کرده
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

    def list_searches(self, only_enabled=False):
        sql = "SELECT * FROM searches"
        if only_enabled:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY created_at DESC"
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql)]

    def get_search(self, search_id):
        with self.lock:
            row = self.conn.execute(
                "SELECT * FROM searches WHERE id = ?", (search_id,)).fetchone()
        return dict(row) if row else None

    def update_search(self, search_id, name=None, params=None, enabled=None):
        """هر سه اختیاری‌اند — فقط چیزی که داده شده نوشته می‌شود."""
        sets, vals = [], []
        if name is not None:
            sets.append("name = ?")
            vals.append(name)
        if params is not None:
            sets.append("params_json = ?")
            vals.append(json.dumps(params, ensure_ascii=False))
        if enabled is not None:
            sets.append("enabled = ?")
            vals.append(1 if enabled else 0)
        if not sets:
            return False
        vals.append(search_id)
        with self.lock:
            cur = self.conn.execute(
                f"UPDATE searches SET {', '.join(sets)} WHERE id = ?", vals)
            self.conn.commit()
        return cur.rowcount > 0

    def mark_search_run(self, search_id):
        with self.lock:
            self.conn.execute("UPDATE searches SET last_run_at = ? WHERE id = ?",
                              (now(), search_id))
            self.conn.commit()

    def delete_search(self, search_id):
        with self.lock:
            self.conn.execute("DELETE FROM searches WHERE id = ?", (search_id,))
            self.conn.commit()

    # --- تنظیمات (قابل تغییر از پنل، خوانده‌شده توسط بات) ---

    def get_setting(self, key, default=None):
        with self.lock:
            row = self.conn.execute("SELECT value FROM settings WHERE key = ?",
                                    (key,)).fetchone()
        return row["value"] if row and row["value"] is not None else default

    def set_setting(self, key, value):
        with self.lock:
            self.conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                              (key, None if value is None else str(value)))
            self.conn.commit()

    def all_settings(self):
        with self.lock:
            return {r["key"]: r["value"] for r in
                    self.conn.execute("SELECT key, value FROM settings")}

    # --- پست‌های فرستاده‌شده توسط بات ---

    def sent_post(self, token, chat_id):
        with self.lock:
            row = self.conn.execute(
                "SELECT * FROM sent_posts WHERE token = ? AND chat_id = ?",
                (token, str(chat_id))).fetchone()
        return dict(row) if row else None

    def sent_tokens(self, chat_id):
        with self.lock:
            return {r["token"] for r in self.conn.execute(
                "SELECT token FROM sent_posts WHERE chat_id = ?", (str(chat_id),))}

    def record_sent(self, token, chat_id, message_id, search_id, score, fre,
                    media_ids=None):
        with self.lock:
            self.conn.execute(
                """INSERT OR REPLACE INTO sent_posts
                   (token, chat_id, message_id, search_id, sent_at, score, last_fre,
                    media_ids)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (token, str(chat_id), message_id, search_id, now(), score, fre,
                 json.dumps(media_ids) if media_ids else None))
            self.conn.commit()

    def sent_media_ids(self, token, chat_id):
        """شناسه پیام‌های گالری یک آگهی — برای حذف کامل، نه فقط پیام متنی."""
        with self.lock:
            row = self.conn.execute(
                "SELECT media_ids FROM sent_posts WHERE token = ? AND chat_id = ?",
                (token, str(chat_id))).fetchone()
        return json.loads(row["media_ids"]) if row and row["media_ids"] else []

    def update_sent_fre(self, token, chat_id, fre):
        with self.lock:
            self.conn.execute(
                "UPDATE sent_posts SET last_fre = ? WHERE token = ? AND chat_id = ?",
                (fre, token, str(chat_id)))
            self.conn.commit()

    # --- اجراهای بات ---

    def start_run(self):
        with self.lock:
            cur = self.conn.execute("INSERT INTO bot_runs (started_at) VALUES (?)", (now(),))
            self.conn.commit()
            return cur.lastrowid

    def finish_run(self, run_id, ok, error=None, sent=0):
        with self.lock:
            self.conn.execute(
                "UPDATE bot_runs SET finished_at = ?, ok = ?, error = ?, sent = ? WHERE id = ?",
                (now(), 1 if ok else 0, error, sent, run_id))
            self.conn.commit()

    def last_runs(self, n=5):
        with self.lock:
            return [dict(r) for r in self.conn.execute(
                "SELECT * FROM bot_runs ORDER BY id DESC LIMIT ?", (n,))]

    def last_ok_run(self):
        with self.lock:
            row = self.conn.execute(
                "SELECT * FROM bot_runs WHERE ok = 1 ORDER BY id DESC LIMIT 1").fetchone()
        return dict(row) if row else None

    def consecutive_failures(self):
        count = 0
        for run in self.last_runs(10):
            if run["finished_at"] is None:
                continue
            if run["ok"]:
                break
            count += 1
        return count

    def post_last_seen(self, token):
        with self.lock:
            row = self.conn.execute(
                "SELECT last_seen FROM posts WHERE token = ?", (token,)).fetchone()
        return row["last_seen"] if row else None

    def snapshot_at(self, token, at):
        """آخرین عکس لحظه‌ای قبل از یک زمان — برای «قیمت وقتی بوکمارک شد»."""
        with self.lock:
            row = self.conn.execute(
                """SELECT deposit, monthly_rent, seen_at FROM snapshots
                   WHERE token = ? AND seen_at <= ? ORDER BY seen_at DESC LIMIT 1""",
                (token, at)).fetchone()
        return dict(row) if row else None
