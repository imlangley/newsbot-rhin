import asyncio
import logging
from datetime import datetime, timezone, timedelta, time

from telegram import Update, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)
from telegram.constants import ParseMode
from html import escape

from config import Config, SITES
from database import Database
from rss_checker import get_new_articles
from ai_summarizer import summarize_article
from formatter import format_telegram_notification

logger = logging.getLogger(__name__)

WIB = timezone(timedelta(hours=7))

# Global database instance
db: Database | None = None


async def post_init(application: Application) -> None:
    """Setup setelah bot start."""
    await application.bot.set_my_commands(
        [
            BotCommand("start", "Mulai & berlangganan notifikasi"),
            BotCommand("stop", "Berhenti berlangganan notifikasi"),
            BotCommand("check", "Cek artikel baru sekarang"),
            BotCommand("today", "Lihat berita hari ini"),
            BotCommand("latest", "Lihat 5 artikel terakhir"),
            BotCommand("status", "Status bot"),
            BotCommand("help", "Bantuan"),
        ]
    )
    logger.info("Bot commands set up")


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start - register subscriber."""
    chat_id = update.effective_chat.id
    username = update.effective_user.username or update.effective_user.first_name

    db.add_subscriber(chat_id, username)
    logger.info("New subscriber: %s (chat_id: %d)", username, chat_id)

    site_list = ", ".join(s["name"] for s in SITES)
    interval = Config.CHECK_INTERVAL_SECONDS // 60

    await update.message.reply_text(
        f"Halo <b>{escape(username)}</b>!\n\n"
        f"Kamu sekarang berlangganan notifikasi artikel baru dari <b>{site_list}</b>.\n\n"
        f"Bot akan cek setiap <b>{interval} menit</b> "
        "dan mengirim rangkuman + format siap post untuk X/Twitter dan Facebook.\n\n"
        "<b>Perintah:</b>\n"
        "/check - Cek artikel baru sekarang\n"
        "/today - Lihat berita hari ini\n"
        "/latest - 5 artikel terakhir\n"
        "/status - Status bot\n"
        "/stop - Berhenti berlangganan\n"
        "/help - Bantuan",
        parse_mode=ParseMode.HTML,
    )


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /stop - unsubscribe."""
    chat_id = update.effective_chat.id
    db.remove_subscriber(chat_id)
    await update.message.reply_text(
        "Kamu sudah berhenti berlangganan. Ketik /start untuk berlangganan lagi."
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help."""
    site_list = "\n".join(f"  - {s['name']} ({s['site_url']})" for s in SITES)
    interval = Config.CHECK_INTERVAL_SECONDS // 60

    await update.message.reply_text(
        "<b>Perintah yang tersedia:</b>\n\n"
        "/start - Mulai & berlangganan notifikasi\n"
        "/stop - Berhenti berlangganan\n"
        "/check - Cek artikel baru sekarang (manual)\n"
        "/today - Lihat semua berita yang sudah diproses hari ini\n"
        "/latest - Lihat 5 artikel terakhir yang sudah diproses\n"
        "/status - Status bot (jumlah subscriber, artikel, dll)\n"
        "/help - Tampilkan pesan ini\n\n"
        f"Bot otomatis cek artikel baru setiap <b>{interval} menit</b>.\n\n"
        f"<b>Sumber berita:</b>\n{site_list}\n\n"
        "Setiap ada artikel baru, bot akan:\n"
        "1. Mengambil konten lengkap artikel\n"
        "2. Merangkum dengan AI\n"
        "3. Membuat caption untuk X/Twitter dan Facebook\n"
        "4. Mengirim notifikasi siap copy-paste\n\n"
        f"Rekap harian otomatis dikirim setiap jam <b>{Config.RECAP_HOUR_WIB}:00 WIB</b>.",
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /status."""
    article_count = db.get_article_count()
    subscriber_count = db.get_subscriber_count()
    interval = Config.CHECK_INTERVAL_SECONDS // 60

    # Hitung artikel hari ini
    today_articles = db.get_today_articles(Config.RECAP_HOUR_WIB)
    today_count = len(today_articles)

    # Info job queue
    jobs = context.job_queue.jobs()
    job_info = "Aktif" if jobs else "Tidak aktif"

    site_list = ", ".join(s["name"] for s in SITES)

    await update.message.reply_text(
        f"<b>Status Bot newsbot-rhin</b>\n\n"
        f"Sumber berita: <b>{site_list}</b>\n"
        f"Artikel hari ini: <b>{today_count}</b>\n"
        f"Total artikel terproses: <b>{article_count}</b>\n"
        f"Subscriber: <b>{subscriber_count}</b>\n"
        f"Interval cek: <b>{interval} menit</b>\n"
        f"AI Model: <b>{Config.AI_MODEL}</b>\n"
        f"Rekap harian: <b>{Config.RECAP_HOUR_WIB}:00 WIB</b>\n"
        f"Scheduler: <b>{job_info}</b>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_latest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /latest - show recent articles."""
    articles = db.get_recent_articles(5)

    if not articles:
        await update.message.reply_text("Belum ada artikel yang diproses.")
        return

    msg = "<b>5 Artikel Terakhir:</b>\n\n"
    for i, art in enumerate(articles, 1):
        source = art.get("source", "?").upper()
        msg += f"{i}. [{source}] <a href='{art['url']}'>{escape(art['title'])}</a>\n"
        msg += f"   {art['posted_at'][:10]}\n\n"

    await update.message.reply_text(
        msg, parse_mode=ParseMode.HTML, disable_web_page_preview=True
    )


async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /today - lihat berita yang sudah diproses hari ini."""
    articles = db.get_today_articles(Config.RECAP_HOUR_WIB)

    if not articles:
        await update.message.reply_text("Belum ada artikel yang diproses hari ini.")
        return

    # Kelompokkan per source
    by_source: dict[str, list[dict]] = {}
    for art in articles:
        src = art.get("source", "unknown")
        by_source.setdefault(src, []).append(art)

    # Kirim per source sebagai bubble terpisah
    for source_slug, arts in by_source.items():
        # Cari nama site dari SITES config
        source_name = source_slug.upper()
        for s in SITES:
            if s["slug"] == source_slug:
                source_name = s["name"]
                break

        msg = f"<b>Berita Hari Ini - {escape(source_name)}</b>\n"
        msg += f"Total: <b>{len(arts)}</b> artikel\n\n"

        for i, art in enumerate(arts, 1):
            msg += f"{i}. <a href='{art['url']}'>{escape(art['title'])}</a>\n"
            # Tampilkan jam diproses (convert ke WIB)
            try:
                posted_utc = datetime.fromisoformat(art["posted_at"])
                posted_wib = posted_utc.astimezone(WIB)
                msg += f"   {posted_wib.strftime('%H:%M WIB')}\n\n"
            except (ValueError, KeyError):
                msg += f"   {art['posted_at'][:16]}\n\n"

        await update.message.reply_text(
            msg, parse_mode=ParseMode.HTML, disable_web_page_preview=True
        )
        await asyncio.sleep(0.3)


async def cmd_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /check - manual check for new articles."""
    await update.message.reply_text("Sedang mengecek artikel baru dari semua sumber...")

    try:
        new_articles = await get_new_articles(db)

        if not new_articles:
            await update.message.reply_text("Tidak ada artikel baru saat ini.")
            return

        await update.message.reply_text(
            f"Ditemukan <b>{len(new_articles)}</b> artikel baru! Sedang merangkum...",
            parse_mode=ParseMode.HTML,
        )

        for article in new_articles:
            await _process_and_send_article(article, context)
            await asyncio.sleep(1)

    except Exception as e:
        logger.error("Manual check failed: %s", e)
        await update.message.reply_text(f"Error saat mengecek: {e}")


async def scheduled_check(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Job yang jalan otomatis setiap interval."""
    logger.info("Running scheduled check at %s", datetime.now(timezone.utc).isoformat())

    try:
        new_articles = await get_new_articles(db)

        if not new_articles:
            logger.info("No new articles found")
            return

        logger.info("Found %d new articles, processing...", len(new_articles))

        for article in new_articles:
            await _process_and_send_article(article, context)
            await asyncio.sleep(1)

    except Exception as e:
        logger.error("Scheduled check failed: %s", e)


async def daily_recap(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Rekap harian - dikirim setiap jam 19:00 WIB ke semua subscriber."""
    logger.info("Running daily recap")

    articles = db.get_today_articles(Config.RECAP_HOUR_WIB)
    subscribers = db.get_subscribers()

    if not subscribers:
        logger.info("No subscribers for daily recap")
        return

    # Kelompokkan per source
    by_source: dict[str, list[dict]] = {}
    for art in articles:
        src = art.get("source", "unknown")
        by_source.setdefault(src, []).append(art)

    total = len(articles)
    now_wib = datetime.now(WIB)
    date_str = now_wib.strftime("%d %B %Y")

    # Buat pesan rekap
    msg = f"<b>Rekap Harian - {date_str}</b>\n\n"
    msg += f"Total artikel diproses hari ini: <b>{total}</b>\n\n"

    if total == 0:
        msg += "Tidak ada artikel baru yang diproses hari ini."
    else:
        for source_slug, arts in by_source.items():
            source_name = source_slug.upper()
            for s in SITES:
                if s["slug"] == source_slug:
                    source_name = s["name"]
                    break

            msg += f"<b>{escape(source_name)}</b>: {len(arts)} artikel\n"
            for i, art in enumerate(arts, 1):
                msg += f"  {i}. {escape(art['title'])}\n"
            msg += "\n"

    msg += f"\n<i>Cutoff: {Config.RECAP_HOUR_WIB}:00 WIB</i>"

    # Kirim ke semua subscriber
    for chat_id in subscribers:
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=msg,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.error("Failed to send recap to chat_id %d: %s", chat_id, e)
            if "blocked" in str(e).lower() or "deactivated" in str(e).lower():
                db.remove_subscriber(chat_id)
                logger.info("Removed inactive subscriber: %d", chat_id)

    logger.info("Daily recap sent to %d subscribers (%d articles)", len(subscribers), total)


async def _process_and_send_article(article, context: ContextTypes.DEFAULT_TYPE):
    """Process satu artikel: summarize lalu kirim ke semua subscriber (1 artikel = 1 bubble chat)."""
    try:
        # Summarize dengan AI
        summary = await summarize_article(article)

        # Format notifikasi Telegram (sudah per-artikel, per-source)
        notification = format_telegram_notification(
            title=article.title,
            url=article.url,
            source_name=article.source_name,
            caption_x=summary["caption_x"],
            caption_fb=summary["caption_fb"],
            hashtags=summary["hashtags"],
            quote=summary.get("quote", ""),
        )

        # Kirim ke semua subscriber - setiap artikel = 1 bubble chat terpisah
        subscribers = db.get_subscribers()
        for chat_id in subscribers:
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=notification,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=False,
                )
                logger.info("Sent notification to chat_id: %d", chat_id)
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.error("Failed to send to chat_id %d: %s", chat_id, e)
                if "blocked" in str(e).lower() or "deactivated" in str(e).lower():
                    db.remove_subscriber(chat_id)
                    logger.info("Removed inactive subscriber: %d", chat_id)

        # Mark sebagai sudah di-post
        db.mark_article_posted(article.url, article.title, article.source_slug)
        logger.info("Article processed and sent: %s (%s)", article.title, article.source_name)

    except Exception as e:
        logger.error("Failed to process article '%s': %s", article.title, e)


def create_bot(database: Database) -> Application:
    """Buat dan konfigurasi bot application."""
    global db
    db = database

    app = (
        Application.builder()
        .token(Config.TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # Register command handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("latest", cmd_latest))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("check", cmd_check))

    # Setup scheduled job - cek RSS setiap interval
    app.job_queue.run_repeating(
        callback=scheduled_check,
        interval=Config.CHECK_INTERVAL_SECONDS,
        first=10,
        name="rss_check",
    )

    # Setup daily recap jam 19:00 WIB (= 12:00 UTC)
    recap_time_utc = time(
        hour=(Config.RECAP_HOUR_WIB - Config.WIB_OFFSET_HOURS) % 24,
        minute=0,
        second=0,
    )
    app.job_queue.run_daily(
        callback=daily_recap,
        time=recap_time_utc,
        name="daily_recap",
    )

    logger.info(
        "Bot configured: check interval %ds, %d sites, daily recap at %d:00 WIB",
        Config.CHECK_INTERVAL_SECONDS,
        len(SITES),
        Config.RECAP_HOUR_WIB,
    )

    return app
