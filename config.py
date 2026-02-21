import os
from dotenv import load_dotenv

load_dotenv()


# Konfigurasi per-site berita
SITES = [
    {
        "name": "RUANG.ID",
        "slug": "ruangid",
        "site_url": "https://www.ruang.id",
        "rss_feed_url": "https://www.ruang.id/feed/",
        "wp_api_url": "https://www.ruang.id/wp-json/wp/v2/posts",
    },
    {
        "name": "CATRAWARTA",
        "slug": "catrawarta",
        "site_url": "https://www.catrawarta.com",
        "rss_feed_url": "https://www.catrawarta.com/feed/",
        "wp_api_url": "https://www.catrawarta.com/wp-json/wp/v2/posts",
    },
    {
        "name": "MABUR.CO",
        "slug": "maburco",
        "site_url": "https://mabur.co",
        "rss_feed_url": "https://mabur.co/feed/",
        "wp_api_url": "https://mabur.co/wp-json/wp/v2/posts",
    },
]


class Config:
    # Telegram
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")

    # AI
    AI_API_URL: str = os.getenv("AI_API_URL", "https://ai.langley.page")
    AI_API_KEY: str = os.getenv("AI_API_KEY", "")
    AI_MODEL: str = os.getenv("AI_MODEL", "gemini-3-pro-low")

    # Scheduler - interval dalam detik (default 1 jam)
    CHECK_INTERVAL_SECONDS: int = int(os.getenv("CHECK_INTERVAL_SECONDS", "3600"))

    # Database
    DB_PATH: str = os.getenv("DB_PATH", "data/bot.db")

    # Timezone offset WIB (UTC+7)
    WIB_OFFSET_HOURS: int = 7

    # Jam cutoff rekap harian (default jam 20:00 WIB)
    RECAP_HOUR_WIB: int = 20
    RECAP_MINUTE_WIB: int = 0
    # slug sumber yang di-auto-post ke X
