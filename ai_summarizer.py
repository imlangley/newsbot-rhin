import json
import logging
import re

import httpx

from config import Config
from rss_checker import Article

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Kamu social media manager. Buat caption repost berita ke X/Twitter dan Facebook.

ATURAN:
- Bahasa Indonesia, interaktif (ajakan baca/komentar)
- Sertakan kutipan tokoh jika ada di artikel
- Caption X: MAKS 180 karakter
- Caption FB: 2-3 kalimat deskriptif
- 3-5 hashtag relevan (tanpa #, nanti ditambah otomatis)
- Jangan copy judul, buat lebih menarik

BALAS HANYA JSON VALID, TANPA code block, TANPA backtick:
{"caption_x":"...","caption_fb":"...","hashtags":["tag1","tag2","tag3"],"quote":"kutipan atau kosong"}"""


def _extract_json(text: str) -> dict | None:
    """Extract JSON dari response AI, handle berbagai format."""
    text = text.strip()

    # 1. Coba langsung parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. Coba extract dari code block ```json ... ``` atau ``` ... ```
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 3. Cari dari { pertama sampai } terakhir
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = text[start : end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            # Coba perbaiki common issues
            candidate = re.sub(r",\s*}", "}", candidate)
            candidate = re.sub(r",\s*]", "]", candidate)
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass

    return None


async def summarize_article(article: Article) -> dict:
    """Kirim artikel ke AI untuk dirangkum jadi caption sosmed."""
    content = article.full_content if article.full_content else article.description

    # Truncate di batas paragraf jika terlalu panjang
    if len(content) > 2000:
        truncated = content[:2000]
        last_period = truncated.rfind(".")
        if last_period > 1500:
            content = truncated[: last_period + 1]
        else:
            content = truncated + "..."

    user_prompt = f"""Buatkan caption untuk repost berita berikut:

SUMBER: {article.source_name}
JUDUL: {article.title}
PENULIS: {article.author}
KATEGORI: {", ".join(article.categories[:5])}

ISI ARTIKEL:
{content}

Balas HANYA JSON, tanpa teks lain."""

    logger.info("Summarizing article: %s (%s)", article.title, article.source_name)

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{Config.AI_API_URL}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {Config.AI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": Config.AI_MODEL,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.5,
                    "max_tokens": 2000,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        ai_response = data["choices"][0]["message"]["content"].strip()
        logger.info("AI raw response length: %d chars", len(ai_response))
        logger.debug("AI raw response: %s", ai_response)

        result = _extract_json(ai_response)

        if result is None:
            logger.error("Could not extract JSON from AI response")
            return _fallback_summary(article)

        # Validasi field yang dibutuhkan
        required_fields = ["caption_x", "caption_fb", "hashtags"]
        for fld in required_fields:
            if fld not in result:
                raise ValueError(f"Missing field: {fld}")

        # Pastikan hashtags adalah list
        if isinstance(result["hashtags"], str):
            result["hashtags"] = [h.strip() for h in result["hashtags"].split(",")]

        # Bersihkan hashtag - tambah # jika belum ada
        result["hashtags"] = [
            f"#{h.lstrip('#').replace(' ', '')}" for h in result["hashtags"]
        ]

        # Pastikan quote ada
        if "quote" not in result:
            result["quote"] = ""

        logger.info("Successfully summarized: %s", article.title)
        return result

    except Exception as e:
        logger.error("AI summarization failed: %s", e)
        return _fallback_summary(article)


def _fallback_summary(article: Article) -> dict:
    """Fallback summary jika AI gagal."""
    caption_x = article.title
    if len(caption_x) > 200:
        caption_x = caption_x[:197] + "..."

    caption_fb = article.description[:500] if article.description else article.title

    # Generate hashtags dari categories + source
    hashtags = [f"#{cat.replace(' ', '')}" for cat in article.categories[:3]]
    hashtags.append(f"#{article.source_name.replace('.', '').replace(' ', '')}")
    if not hashtags:
        hashtags = ["#Berita", "#Indonesia"]

    return {
        "caption_x": caption_x,
        "caption_fb": caption_fb,
        "hashtags": hashtags,
        "quote": "",
    }
