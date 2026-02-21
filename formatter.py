"""Format caption untuk X/Twitter."""

from html import escape


def format_post(paragraphs: str, url: str, cta: str = "") -> str:
    """
    Format X single post: paragraphs + link + CTA
    Total maks 280 char (URL selalu dihitung 23 char oleh X)
    """
    url_length = 23
    # overhead: \n sebelum url, \n sebelum cta, \n\n antar bagian
    # struktur: paragraphs\n\nurl\n\ncta
    overhead = 2 + url_length + (2 + len(cta) if cta else 0)
    max_para = 280 - overhead

    if len(paragraphs) > max_para:
        # cari titik terakhir sebelum batas
        trimmed = paragraphs[:max_para]
        last_period = max(trimmed.rfind("."), trimmed.rfind("!"), trimmed.rfind("?"))
        if last_period > max_para // 2:
            paragraphs = trimmed[: last_period + 1].strip()
        else:
            # ga ada titik yang cukup dekat, potong di spasi
            last_space = trimmed.rfind(" ")
            paragraphs = (
                trimmed[:last_space].strip() if last_space > 0 else trimmed.strip()
            )

    parts = [paragraphs]
    if cta:
        parts.append(cta)
    parts.append(url)
    post = "\n\n".join(parts)

    return post


def format_telegram_notification(
    title: str,
    url: str,
    source_name: str,
    caption: str,
    hashtags: list[str],
    source_slug: str = "",
    hook: str = "",
    paragraphs: str = "",
    cta: str = "",
    body: str = "",
) -> str:
    """Format notifikasi Telegram — siap copy paste ke X."""
    main_text = paragraphs or body or hook or caption
    post = format_post(main_text, url, cta)

    safe_title = escape(title)
    safe_source = escape(source_name)

    source_hashtag_map = {
        "ruangid": "#Ruang",
        "catrawarta": "#Catra",
        "maburco": "#Mabur",
    }
    hashtag_telegram = source_hashtag_map.get(source_slug, f"#{source_slug}")

    msg = (
        f"<b>{safe_source}</b>\n"
        f"<b>{safe_title}</b>\n\n"
        f"<pre>{post}</pre>\n\n"
        f"{hashtag_telegram}"
    )

    return msg
