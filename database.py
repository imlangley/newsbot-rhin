import sqlite3
import os
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

WIB = timezone(timedelta(hours=7))


class Database:
    def __init__(self, db_path: str):
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self.db_path = db_path
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        conn = self._get_conn()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS posted_articles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT UNIQUE NOT NULL,
                    title TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'ruangid',
                    posted_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS subscribers (
                    chat_id INTEGER PRIMARY KEY,
                    username TEXT,
                    subscribed_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_articles_url ON posted_articles(url);
                CREATE INDEX IF NOT EXISTS idx_articles_source ON posted_articles(source);
            """)
            # Migrasi: tambah kolom source jika belum ada (untuk DB lama)
            try:
                conn.execute("SELECT source FROM posted_articles LIMIT 1")
            except sqlite3.OperationalError:
                conn.execute(
                    "ALTER TABLE posted_articles ADD COLUMN source TEXT NOT NULL DEFAULT 'ruangid'"
                )
            conn.commit()
            logger.info("Database initialized at %s", self.db_path)
        finally:
            conn.close()

    def is_article_posted(self, url: str) -> bool:
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT 1 FROM posted_articles WHERE url = ?", (url,)
            ).fetchone()
            return row is not None
        finally:
            conn.close()

    def mark_article_posted(self, url: str, title: str, source: str = "ruangid"):
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO posted_articles (url, title, source, posted_at) VALUES (?, ?, ?, ?)",
                (url, title, source, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
        finally:
            conn.close()

    def get_recent_articles(self, limit: int = 5, source: str | None = None) -> list[dict]:
        conn = self._get_conn()
        try:
            if source:
                rows = conn.execute(
                    "SELECT url, title, source, posted_at FROM posted_articles WHERE source = ? ORDER BY id DESC LIMIT ?",
                    (source, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT url, title, source, posted_at FROM posted_articles ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_articles_since(self, since_utc: str) -> list[dict]:
        """Ambil semua artikel yang diproses sejak timestamp tertentu (UTC ISO format)."""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT url, title, source, posted_at FROM posted_articles WHERE posted_at >= ? ORDER BY id ASC",
                (since_utc,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_today_articles(self, recap_hour: int = 19) -> list[dict]:
        """Ambil artikel hari ini berdasarkan cutoff jam recap_hour WIB.

        Periode: kemarin jam recap_hour WIB sampai sekarang.
        Contoh: cutoff jam 19 -> dari kemarin 19:00 WIB sampai sekarang.
        """
        now_wib = datetime.now(WIB)
        today_cutoff = now_wib.replace(hour=recap_hour, minute=0, second=0, microsecond=0)

        # Jika sekarang belum lewat jam cutoff, pakai cutoff kemarin
        if now_wib < today_cutoff:
            start = today_cutoff - timedelta(days=1)
        else:
            start = today_cutoff

        # Convert ke UTC ISO string untuk query
        start_utc = start.astimezone(timezone.utc).isoformat()
        return self.get_articles_since(start_utc)

    def get_article_count(self) -> int:
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT COUNT(*) as cnt FROM posted_articles").fetchone()
            return row["cnt"]
        finally:
            conn.close()

    def add_subscriber(self, chat_id: int, username: str | None = None):
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO subscribers (chat_id, username, subscribed_at) VALUES (?, ?, ?)",
                (chat_id, username, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
        finally:
            conn.close()

    def remove_subscriber(self, chat_id: int):
        conn = self._get_conn()
        try:
            conn.execute("DELETE FROM subscribers WHERE chat_id = ?", (chat_id,))
            conn.commit()
        finally:
            conn.close()

    def get_subscribers(self) -> list[int]:
        conn = self._get_conn()
        try:
            rows = conn.execute("SELECT chat_id FROM subscribers").fetchall()
            return [r["chat_id"] for r in rows]
        finally:
            conn.close()

    def get_subscriber_count(self) -> int:
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT COUNT(*) as cnt FROM subscribers").fetchone()
            return row["cnt"]
        finally:
            conn.close()
