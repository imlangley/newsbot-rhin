import json
import logging
import re

import httpx

from config import Config
from rss_checker import Article

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Kamu social media manager profesional. Buat caption repost berita ke X/Twitter yang engaging dan fit dalam 280 karakter.

ATURAN CAPTION:
- Bahasa Indonesia natural, pakai hook yang kuat di awal (pertanyaan provokatif, fakta mengejutkan, atau statement bold)
- Fokus pada esensi/takeaway paling menarik dari artikel, BUKAN sekadar merangkum
- PANJANG MAKSIMAL: 100-120 karakter (PENTING! harus singkat karena ada URL + hashtag)
- JANGAN copy-paste judul artikel
- Pastikan info penting (nama tokoh, angka, lokasi) TIDAK terpotong

ATURAN QUOTE:
- HANYA sertakan quote jika benar-benar powerful dan crucial (kalau tidak ada yang powerful, kosongkan)
- Kalau ada quote: maksimal 70 karakter, potong dengan "..." jika perlu
- Format: "kutipan..." - Nama
- Lebih baik skip quote daripada bikin post over 280 karakter

ATURAN HASHTAG:
- HANYA 2 hashtag yang paling relevan
- Pilih yang recognizable, bukan terlalu spesifik
- Total panjang 2 hashtag: maksimal 25 karakter
- Tanpa simbol # (akan ditambah otomatis)

CONTOH GOOD HOOK (singkat & ngena):
❌ "Artikel membahas tentang kondisi kampus..." (terlalu panjang)
✅ "Kampus top tapi gak ramah difabel. Kenapa?" (singkat, provokatif)
❌ "Pemerintah umumkan kebijakan baru untuk petani..." (bertele-tele)
✅ "10 juta petani tertolong. Tapi cukup gak?" (padat, bikin penasaran)

TARGET TOTAL POST:
Caption (120) + Quote (70) + URL (23) + Hashtags (25) + line breaks (10) = ~248 karakter (aman!)

BALAS HANYA JSON VALID, TANPA code block, TANPA backtick:
{"caption":"...","hashtags":["tag1","tag2"],"quote":"kutipan singkat atau kosong"}"""


def _extract_json(text: str) -> dict | None:
    """Extract JSON dari response AI, handle berbagai format."""
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = text[start : end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
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

        # Support old format (caption_x/caption_fb) dan new format (caption)
        if "caption" not in result:
            if "caption_x" in result:
                result["caption"] = result["caption_x"]
            elif "caption_fb" in result:
                result["caption"] = result["caption_fb"]
            else:
                raise ValueError("Missing field: caption")

        if "hashtags" not in result:
            raise ValueError("Missing field: hashtags")

        # Pastikan hashtags adalah list
        if isinstance(result["hashtags"], str):
            result["hashtags"] = [h.strip() for h in result["hashtags"].split(",")]

        # Bersihkan hashtag
        result["hashtags"] = [
            f"#{h.lstrip('#').replace(' ', '')}" for h in result["hashtags"]
        ]

        if "quote" not in result:
            result["quote"] = ""

        logger.info("Successfully summarized: %s", article.title)
        return result

    except Exception as e:
        logger.error("AI summarization failed: %s", e)
        return _fallback_summary(article)


def _fallback_summary(article: Article) -> dict:
    """Fallback summary jika AI gagal."""
    caption = article.title
    if len(caption) > 250:
        caption = caption[:247] + "..."

    hashtags = [f"#{cat.replace(' ', '')}" for cat in article.categories[:3]]
    hashtags.append(f"#{article.source_name.replace('.', '').replace(' ', '')}")
    if not hashtags:
        hashtags = ["#Berita", "#Indonesia"]

    return {
        "caption": caption,
        "hashtags": hashtags,
        "quote": "",
    }
