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

                CREATE TABLE IF NOT EXISTS x_reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    article_url TEXT NOT NULL,
                    article_title TEXT NOT NULL,
                    chat_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    posted_to_x INTEGER DEFAULT 0,
                    reminded INTEGER DEFAULT 0,
                    UNIQUE(article_url, chat_id)
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

    def get_article_id(self, url: str) -> int | None:
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT id FROM posted_articles WHERE url = ?", (url,)
            ).fetchone()
            return row["id"] if row else None
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
        """Ambil artikel yang di-publish HARI INI berdasarkan published_at dari web aslinya."""
        now_wib = datetime.now(WIB)
        start_of_day_wib = now_wib.replace(hour=0, minute=0, second=0, microsecond=0)
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

    def get_today_articles_for_recap(self, recap_hour: int = 20, recap_minute: int = 0) -> list[dict]:
        """Ambil artikel rekap berdasarkan waktu publish web: 00:00 WIB sampai cutoff recap."""
        now_wib = datetime.now(WIB)
        start_of_day_wib = now_wib.replace(hour=0, minute=0, second=0, microsecond=0)
        cutoff_wib = start_of_day_wib.replace(hour=recap_hour, minute=recap_minute)

        # Jika dipanggil sebelum jam cutoff (manual), batasi sampai waktu saat ini
        if now_wib < cutoff_wib:
            cutoff_wib = now_wib

        start_utc = start_of_day_wib.astimezone(timezone.utc).isoformat()
        cutoff_utc = cutoff_wib.astimezone(timezone.utc).isoformat()

        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT url, title, source, published_at, posted_at FROM posted_articles "
                "WHERE published_at IS NOT NULL AND published_at >= ? AND published_at <= ? "
                "ORDER BY published_at ASC",
                (start_utc, cutoff_utc),
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

    def add_x_reminder(self, article_url: str, article_title: str, chat_id: int, message_id: int):
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO x_reminders
                   (article_url, article_title, chat_id, message_id, created_at, posted_to_x, reminded)
                   VALUES (?, ?, ?, ?, ?, 0, 0)""",
                (article_url, article_title, chat_id, message_id,
                 datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
        finally:
            conn.close()

    def get_x_reminder_id(self, article_url: str, chat_id: int) -> int | None:
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT id FROM x_reminders WHERE article_url = ? AND chat_id = ?",
                (article_url, chat_id),
            ).fetchone()
            return row["id"] if row else None
        finally:
            conn.close()

    def mark_x_posted(self, article_url: str, chat_id: int):
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE x_reminders SET posted_to_x = 1 WHERE article_url = ? AND chat_id = ?",
                (article_url, chat_id),
            )
            conn.commit()
        finally:
            conn.close()

    def mark_x_posted_by_id(self, reminder_id: int, chat_id: int):
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE x_reminders SET posted_to_x = 1 WHERE id = ? AND chat_id = ?",
                (reminder_id, chat_id),
            )
            conn.commit()
        finally:
            conn.close()

    def get_pending_x_reminders(self, older_than_minutes: int = 30) -> list[dict]:
        """Ambil reminders yang belum dipost dan belum diremind, lebih dari N menit lalu."""
        conn = self._get_conn()
        try:
            cutoff = (datetime.now(timezone.utc) - timedelta(minutes=older_than_minutes)).isoformat()
            rows = conn.execute(
                """SELECT * FROM x_reminders
                   WHERE posted_to_x = 0 AND reminded = 0 AND created_at <= ?""",
                (cutoff,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def mark_x_reminded(self, article_url: str, chat_id: int):
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE x_reminders SET reminded = 1 WHERE article_url = ? AND chat_id = ?",
                (article_url, chat_id),
            )
            conn.commit()
        finally:
            conn.close()
