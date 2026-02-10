import logging
import re
import email.utils
from urllib.parse import urlparse
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

import feedparser
import httpx
from bs4 import BeautifulSoup

from config import SITES
from database import Database

logger = logging.getLogger(__name__)


@dataclass
class Article:
    title: str
    url: str
    author: str
    source_name: str
    source_slug: str
    categories: list[str] = field(default_factory=list)
    description: str = ""
    full_content: str = ""
    pub_date: str = ""           # raw dari RSS
    published_at: str | None = None  # ISO format UTC (parsed dari pub_date)


def _clean_url(url: str) -> str:
    """Hapus UTM parameters dari URL."""
    parsed = urlparse(url)
    clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    clean = re.sub(r"/+$", "/", clean)
    return clean


def _extract_slug(url: str) -> str:
    """Extract slug dari URL WordPress."""
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    parts = path.split("/")
    return parts[-1] if parts else ""


def _strip_html(html: str) -> str:
    """Strip HTML tags dan kembalikan teks bersih."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _parse_pub_date(raw: str) -> str | None:
    """Parse RSS published date ke ISO format UTC."""
    if not raw:
        return None
    try:
        dt = email.utils.parsedate_to_datetime(raw)
        return dt.astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError):
        return None


async def fetch_rss_feed(site: dict) -> list[Article]:
    """Fetch dan parse RSS feed dari satu site."""
    rss_url = site["rss_feed_url"]
    logger.info("Fetching RSS feed: %s", rss_url)

    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(rss_url)
            resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.error("Failed to fetch RSS from %s: %s", site["name"], e)
        return []

    feed = feedparser.parse(resp.text)
    articles = []

    for entry in feed.entries:
        categories = [tag.term for tag in getattr(entry, "tags", [])]
        description = _strip_html(entry.get("summary", ""))
        raw_pub = entry.get("published", "")

        article = Article(
            title=entry.get("title", ""),
            url=_clean_url(entry.get("link", "")),
            author=entry.get("author", ""),
            source_name=site["name"],
            source_slug=site["slug"],
            categories=categories,
            description=description,
            pub_date=raw_pub,
            published_at=_parse_pub_date(raw_pub),
        )
        articles.append(article)

    logger.info("Found %d articles from %s", len(articles), site["name"])
    return articles


async def fetch_full_content(article: Article, wp_api_url: str) -> Article:
    """Fetch konten lengkap artikel via WP REST API."""
    slug = _extract_slug(article.url)
    if not slug:
        logger.warning("Could not extract slug from URL: %s", article.url)
        return article

    logger.info("Fetching full content for slug: %s (%s)", slug, article.source_name)

    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(
                wp_api_url,
                params={"slug": slug, "_fields": "content"},
            )
            resp.raise_for_status()
            data = resp.json()

        if data and isinstance(data, list) and len(data) > 0:
            content_html = data[0].get("content", {}).get("rendered", "")
            article.full_content = _strip_html(content_html)
            logger.info(
                "Got full content for '%s' (%d chars)",
                article.title,
                len(article.full_content),
            )
        else:
            logger.warning("No content found via WP API for slug: %s", slug)
    except Exception as e:
        logger.error("Failed to fetch full content for '%s': %s", article.title, e)

    return article


async def get_new_articles(db: Database, max_age_days: int = 2) -> list[Article]:
    """Cek RSS feed dari SEMUA site dan return artikel yang belum pernah di-post."""
    all_new = []
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=max_age_days)

    for site in SITES:
        try:
            articles = await fetch_rss_feed(site)

            for article in articles:
                if db.is_article_posted(article.url):
                    continue

                # Filter artikel yang terlalu lama (> max_age_days)
                if article.published_at:
                    try:
                        pub_dt = datetime.fromisoformat(article.published_at)
                        if pub_dt < cutoff_date:
                            logger.info(
                                "Skipping old article from %s: %s (published: %s)",
                                site["name"],
                                article.title,
                                pub_dt.strftime("%Y-%m-%d"),
                            )
                            continue
                    except (ValueError, TypeError):
                        pass

                article = await fetch_full_content(article, site["wp_api_url"])
                all_new.append(article)
                logger.info("New article from %s: %s", site["name"], article.title)

        except Exception as e:
            logger.error("Error checking site %s: %s", site["name"], e)

    logger.info("Total new articles from all sites: %d", len(all_new))
    return all_new
