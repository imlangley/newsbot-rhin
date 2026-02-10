#!/usr/bin/env python3
"""
newsbot-rhin - Multi-source News Repost Bot
- Monitors multiple WordPress sites (ruang.id, catrawarta.com, mabur.co)
- Summarizes articles using AI
- Sends Telegram notifications with copy-paste ready captions
  for X/Twitter and Facebook
"""

import logging
import os
import sys

from config import Config, SITES
from database import Database
from bot import create_bot

# Buat data directory sebelum setup logging
os.makedirs("data", exist_ok=True)

# Setup logging
logging.basicConfig(
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("data/bot.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# Reduce noise from libraries
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


def main():
    # Validate config
    if not Config.TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is not set!")
        sys.exit(1)
    if not Config.AI_API_KEY:
        logger.error("AI_API_KEY is not set!")
        sys.exit(1)

    logger.info("=" * 50)
    logger.info("newsbot-rhin Starting...")
    logger.info("Monitoring %d sites:", len(SITES))
    for site in SITES:
        logger.info("  - %s (%s)", site["name"], site["rss_feed_url"])
    logger.info("AI Model: %s", Config.AI_MODEL)
    logger.info("Check Interval: %d seconds", Config.CHECK_INTERVAL_SECONDS)
    logger.info("=" * 50)

    # Initialize database
    database = Database(Config.DB_PATH)

    # Create and run bot
    app = create_bot(database)

    logger.info("Bot is running! Press Ctrl+C to stop.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
