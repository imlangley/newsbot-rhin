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
                    published_at TEXT,
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
            # Migrasi: tambah kolom jika belum ada (untuk DB lama)
            for col, default in [
                ("source", "'ruangid'"),
                ("published_at", "NULL"),
            ]:
                try:
                    conn.execute(f"SELECT {col} FROM posted_articles LIMIT 1")
                except sqlite3.OperationalError:
                    conn.execute(
                        f"ALTER TABLE posted_articles ADD COLUMN {col} TEXT DEFAULT {default}"
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

    def mark_article_posted(self, url: str, title: str, source: str = "ruangid", published_at: str | None = None):
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO posted_articles (url, title, source, published_at, posted_at) VALUES (?, ?, ?, ?, ?)",
                (url, title, source, published_at, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
        finally:
            conn.close()

    def get_recent_articles(self, limit: int = 5, source: str | None = None) -> list[dict]:
        conn = self._get_conn()
        try:
            if source:
                rows = conn.execute(
                    "SELECT url, title, source, published_at, posted_at FROM posted_articles WHERE source = ? ORDER BY id DESC LIMIT ?",
                    (source, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT url, title, source, published_at, posted_at FROM posted_articles ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_today_articles(self, recap_hour: int = 19) -> list[dict]:
        """Ambil artikel yang di-publish HARI INI berdasarkan published_at dari web aslinya.

        Menggunakan tanggal WIB hari ini (00:00 - 23:59 WIB).
        """
        now_wib = datetime.now(WIB)
        # Awal hari ini WIB (00:00:00)
        start_of_day_wib = now_wib.replace(hour=0, minute=0, second=0, microsecond=0)
        # Convert ke UTC
        start_utc = start_of_day_wib.astimezone(timezone.utc).isoformat()

        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT url, title, source, published_at, posted_at FROM posted_articles "
                "WHERE published_at IS NOT NULL AND published_at >= ? "
                "ORDER BY published_at ASC",
                (start_utc,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_today_articles_for_recap(self, recap_hour: int = 19, recap_minute: int = 30) -> list[dict]:
        """Ambil artikel untuk rekap harian dari 00:00 WIB hari ini sampai sekarang.

        Rekap "hari ini" = artikel yang di-post bot dari jam 00:00:00 WIB sampai sekarang.
        Cutoff ditampilkan sebagai recap_hour:recap_minute WIB untuk informasi user.
        """
        now_wib = datetime.now(WIB)
        # Awal hari ini WIB (00:00:00)
        start_of_day_wib = now_wib.replace(hour=0, minute=0, second=0, microsecond=0)
        # Convert ke UTC
        start_utc = start_of_day_wib.astimezone(timezone.utc).isoformat()

        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT url, title, source, published_at, posted_at FROM posted_articles "
                "WHERE posted_at >= ? ORDER BY posted_at ASC",
                (start_utc,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

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
