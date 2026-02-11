"""Format caption untuk sosial media (X/Twitter & Facebook)."""

from html import escape


def format_post(caption: str, url: str, hashtags: list[str], quote: str = "") -> str:
    """
    Format post untuk X/Twitter & Facebook (sama).
    Struktur: caption + link + hashtags
    Maks total: 280 karakter (estimasi X)
    """
    hashtag_str = " ".join(hashtags)
    url_length = 23  # X menghitung semua URL sebagai 23 karakter (t.co)

    if quote:
        # Strip tanda petik dari AI kalau ada (prevent double quotes)
        quote = quote.strip('"').strip('"').strip('"')
        post = f'"{quote}"\n\n{caption}\n\n{url}\n\n{hashtag_str}'
    else:
        post = f"{caption}\n\n{url}\n\n{hashtag_str}"

    # Cek panjang (estimasi - URL dihitung 23 char oleh X)
    estimated_length = len(post) - len(url) + url_length
    if estimated_length > 280:
        excess = estimated_length - 280
        if len(caption) > excess + 3:
            caption = caption[: len(caption) - excess - 3] + "..."
        else:
            caption = caption[:50] + "..."
        if quote:
            post = f'"{quote}"\n\n{caption}\n\n{url}\n\n{hashtag_str}'
        else:
            post = f"{caption}\n\n{url}\n\n{hashtag_str}"

    return post


def format_telegram_notification(
    title: str,
    url: str,
    source_name: str,
    caption: str,
    hashtags: list[str],
    quote: str = "",
    source_slug: str = "",
) -> str:
    """Format notifikasi untuk Telegram - siap copy paste dengan tombol copy."""
    post = format_post(caption, url, hashtags, quote)

    safe_title = escape(title)
    safe_source = escape(source_name)

    # Hashtag sumber untuk searchable di Telegram
    # Mapping slug ke hashtag
    source_hashtag_map = {
        "ruangid": "#Ruang",
        "catrawarta": "#Catra",
        "maburco": "#Mabur"
    }
    hashtag_telegram = source_hashtag_map.get(source_slug, f"#{source_slug}")

    # <pre> tag = otomatis muncul tombol Copy di Telegram mobile & desktop
    # JANGAN escape isi <pre> karena plain text (tanda petik quote jadi dobel kalau di-escape)
    msg = (
        f"<b>{safe_source}</b>\n"
        f"<b>{safe_title}</b>\n\n"
        f"<pre>{post}</pre>\n\n"
        f"{hashtag_telegram}"
    )

    return msg
