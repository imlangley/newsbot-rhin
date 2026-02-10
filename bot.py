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
            BotCommand("recap", "Trigger rekap harian manual"),
            BotCommand("today", "Lihat berita hari ini (semua sumber)"),
            BotCommand("ruang", "Lihat berita hari ini dari RUANG.ID"),
            BotCommand("catra", "Lihat berita hari ini dari CATRAWARTA"),
            BotCommand("mabur", "Lihat berita hari ini dari MABUR.CO"),
            BotCommand("latest", "Lihat 5 artikel terakhir"),
            BotCommand("status", "Status bot"),
            BotCommand("help", "Bantuan"),
        ]
    )
    logger.info("Bot commands set up")


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start - register subscriber."""
    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type
    username = update.effective_user.username or update.effective_user.first_name

    db.add_subscriber(chat_id, username)
    logger.info("New subscriber: %s (chat_id: %d, type: %s)", username, chat_id, chat_type)

    site_list = ", ".join(s["name"] for s in SITES)
    interval = Config.CHECK_INTERVAL_SECONDS // 60

    msg = (
        f"Halo <b>{escape(username)}</b>!\n\n"
        f"Kamu sekarang berlangganan notifikasi artikel baru dari <b>{site_list}</b>.\n\n"
        f"Bot akan cek setiap <b>{interval} menit</b> "
        "dan mengirim rangkuman + format siap post untuk X/Twitter dan Facebook.\n\n"
        "<b>Perintah:</b>\n"
        "/check - Cek artikel baru sekarang\n"
        "/today - Lihat berita hari ini (semua sumber)\n"
        "/ruang - Berita hari ini dari RUANG.ID\n"
        "/catra - Berita hari ini dari CATRAWARTA\n"
        "/mabur - Berita hari ini dari MABUR.CO\n"
        "/latest - 5 artikel terakhir\n"
        "/status - Status bot\n"
        "/stop - Berhenti berlangganan\n"
        "/help - Bantuan"
    )

    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


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

    msg = (
        "<b>Perintah yang tersedia:</b>\n\n"
        "/start - Mulai & berlangganan notifikasi\n"
        "/stop - Berhenti berlangganan\n"
        "/check - Cek artikel baru sekarang (manual)\n"
        "/today - Lihat semua berita hari ini\n"
        "/ruang - Berita hari ini dari RUANG.ID\n"
        "/catra - Berita hari ini dari CATRAWARTA\n"
        "/mabur - Berita hari ini dari MABUR.CO\n"
        "/latest - Lihat 5 artikel terakhir\n"
        "/status - Status bot\n"
        "/help - Tampilkan pesan ini\n\n"
        f"Bot otomatis cek artikel baru setiap <b>{interval} menit</b>.\n\n"
        f"<b>Sumber berita:</b>\n{site_list}\n\n"
        f"Rekap harian otomatis dikirim setiap jam <b>{Config.RECAP_HOUR_WIB}:{Config.RECAP_MINUTE_WIB:02d} WIB</b>."
    )

    await update.message.reply_text(
        msg, parse_mode=ParseMode.HTML, disable_web_page_preview=True
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /status."""
    article_count = db.get_article_count()
    subscriber_count = db.get_subscriber_count()
    interval = Config.CHECK_INTERVAL_SECONDS // 60

    today_articles = db.get_today_articles(Config.RECAP_HOUR_WIB)
    today_count = len(today_articles)

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
        pub_str = _format_published_time(art)
        msg += f"{i}. [{source}] <a href='{art['url']}'>{escape(art['title'])}</a>\n"
        msg += f"   {pub_str}\n\n"

    await update.message.reply_text(
        msg, parse_mode=ParseMode.HTML, disable_web_page_preview=True
    )


def _format_published_time(art: dict) -> str:
    """Format waktu publish artikel ke WIB. Pakai published_at dari web asli."""
    pub = art.get("published_at")
    if pub:
        try:
            dt = datetime.fromisoformat(pub).astimezone(WIB)
            return dt.strftime("%d/%m/%Y %H:%M WIB")
        except (ValueError, TypeError):
            pass
    # Fallback ke posted_at
    try:
        dt = datetime.fromisoformat(art["posted_at"]).astimezone(WIB)
        return dt.strftime("%d/%m/%Y %H:%M WIB")
    except (ValueError, KeyError, TypeError):
        return art.get("posted_at", "?")[:16]


def _render_article_list(articles: list[dict], source_name: str) -> str:
    """Render daftar artikel jadi pesan Telegram."""
    msg = f"<b>Berita Hari Ini - {escape(source_name)}</b>\n"
    msg += f"Total: <b>{len(articles)}</b> artikel\n\n"

    for i, art in enumerate(articles, 1):
        pub_str = _format_published_time(art)
        msg += f"{i}. <a href='{art['url']}'>{escape(art['title'])}</a>\n"
        msg += f"   {pub_str}\n\n"

    return msg


async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /today - lihat berita hari ini (semua source)."""
    articles = db.get_today_articles(Config.RECAP_HOUR_WIB)

    if not articles:
        await update.message.reply_text("Belum ada artikel yang di-publish hari ini.")
        return

    # Kelompokkan per source
    by_source: dict[str, list[dict]] = {}
    for art in articles:
        src = art.get("source", "unknown")
        by_source.setdefault(src, []).append(art)

    # Kirim per source sebagai bubble terpisah
    for source_slug, arts in by_source.items():
        source_name = _get_source_name(source_slug)
        msg = _render_article_list(arts, source_name)

        await update.message.reply_text(
            msg, parse_mode=ParseMode.HTML, disable_web_page_preview=True
        )
        await asyncio.sleep(0.3)


async def cmd_source_today(update: Update, context: ContextTypes.DEFAULT_TYPE, source_slug: str) -> None:
    """Helper: lihat berita hari ini dari 1 source saja."""
    articles = db.get_today_articles(Config.RECAP_HOUR_WIB)
    filtered = [a for a in articles if a.get("source") == source_slug]
    source_name = _get_source_name(source_slug)

    if not filtered:
        await update.message.reply_text(f"Belum ada artikel dari {source_name} yang di-publish hari ini.")
        return

    msg = _render_article_list(filtered, source_name)
    await update.message.reply_text(
        msg, parse_mode=ParseMode.HTML, disable_web_page_preview=True
    )


def _get_source_name(source_slug: str) -> str:
    """Cari nama site dari slug."""
    for s in SITES:
        if s["slug"] == source_slug:
            return s["name"]
    return source_slug.upper()


async def cmd_ruang(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_source_today(update, context, "ruangid")


async def cmd_catra(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_source_today(update, context, "catrawarta")


async def cmd_mabur(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_source_today(update, context, "maburco")


async def cmd_recap(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /recap - trigger manual daily recap."""
    await update.message.reply_text("Generating daily recap...")
    await daily_recap(context)


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
    """Rekap harian - dikirim setiap jam 19:30 WIB ke semua subscriber."""
    logger.info("Running daily recap")

    articles = db.get_today_articles_for_recap(Config.RECAP_HOUR_WIB)
    subscribers = db.get_subscribers()

    if not subscribers:
        logger.info("No subscribers for daily recap")
        return

    by_source: dict[str, list[dict]] = {}
    for art in articles:
        src = art.get("source", "unknown")
        by_source.setdefault(src, []).append(art)

    total = len(articles)
    now_wib = datetime.now(WIB)
    date_str = now_wib.strftime("%d %B %Y")
    cutoff_str = f"{Config.RECAP_HOUR_WIB}:{Config.RECAP_MINUTE_WIB:02d} WIB"

    # Ringkasan rekap harian
    msg = f"<b>Rekap Harian - {date_str}</b>\n\n"
    if total == 0:
        msg += "Tidak ada artikel baru yang diproses hari ini."
    else:
        for source_slug in by_source:
            source_name = _get_source_name(source_slug)
            count = len(by_source[source_slug])
            msg += f"{escape(source_name)}: <b>{count}</b> artikel\n"
        msg += f"\nTotal: <b>{total}</b> artikel"
    msg += f"\n\n<i>Cutoff: {cutoff_str}</i>"

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
        # Mark as posted SEBELUM process (prevent race condition)
        db.mark_article_posted(
            article.url, article.title, article.source_slug,
            published_at=article.published_at,
        )
        logger.info("Marked as posted (before processing): %s (%s)", article.title, article.source_name)

        # Summarize dengan AI
        summary = await summarize_article(article)

        # Format notifikasi Telegram (1 caption untuk X & FB)
        notification = format_telegram_notification(
            title=article.title,
            url=article.url,
            source_name=article.source_name,
            caption=summary["caption"],
            hashtags=summary["hashtags"],
            quote=summary.get("quote", ""),
        )

        # Kirim ke semua subscriber
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
    app.add_handler(CommandHandler("ruang", cmd_ruang))
    app.add_handler(CommandHandler("catra", cmd_catra))
    app.add_handler(CommandHandler("mabur", cmd_mabur))
    app.add_handler(CommandHandler("check", cmd_check))
    app.add_handler(CommandHandler("recap", cmd_recap))

    # Setup scheduled job - cek RSS setiap interval
    app.job_queue.run_repeating(
        callback=scheduled_check,
        interval=Config.CHECK_INTERVAL_SECONDS,
        first=10,
        name="rss_check",
    )

    # Setup daily recap jam 19:30 WIB (= 12:30 UTC)
    recap_time_utc = time(
        hour=(Config.RECAP_HOUR_WIB - Config.WIB_OFFSET_HOURS) % 24,
        minute=Config.RECAP_MINUTE_WIB,
        second=0,
    )
    app.job_queue.run_daily(
        callback=daily_recap,
        time=recap_time_utc,
        name="daily_recap",
    )

    logger.info(
        "Bot configured: check interval %ds, %d sites, daily recap at %d:%02d WIB",
        Config.CHECK_INTERVAL_SECONDS,
        len(SITES),
        Config.RECAP_HOUR_WIB,
        Config.RECAP_MINUTE_WIB,
    )

    return app
