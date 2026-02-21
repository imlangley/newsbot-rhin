import json
import logging
import re

import httpx

from config import Config
from rss_checker import Article

logger = logging.getLogger(__name__)

X_CHAR_LIMIT = 280
X_URL_LENGTH = 23

SYSTEM_PROMPT = """Kamu editor konten X (Twitter) untuk berita.

OUTPUT WAJIB JSON valid, tanpa markdown, tanpa teks lain:
{"paragraphs":"isi","cta":"isi"}

ATURAN:
- paragraphs wajib 2 paragraf, dipisah tepat satu baris kosong (\n\n).
- paragraphs harus mengambil inti fakta dari artikel, tidak menambah opini baru.
- gaya bahasa lugas, informatif, tanpa emoji, tanpa bahasa gaul.
- cta 1 kalimat singkat untuk ajak baca link, tanpa emoji."""


def _extract_json(text: str) -> dict | None:
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

    lower = text.lower()
    p_idx = lower.find('"paragraphs"')
    c_idx = lower.find('"cta"')
    if p_idx != -1 and c_idx != -1 and c_idx > p_idx:
        p_seg = text[p_idx:c_idx]
        c_seg = text[c_idx:]

        p_colon = p_seg.find(":")
        c_colon = c_seg.find(":")
        if p_colon != -1 and c_colon != -1:
            paragraphs = p_seg[p_colon + 1 :].strip().rstrip(",").strip()
            cta = c_seg[c_colon + 1 :].strip().rstrip("}").strip()

            paragraphs = paragraphs.strip('"').replace("\\n", "\n").strip()
            cta = cta.strip('"').replace("\\n", " ").strip()
            if paragraphs:
                return {"paragraphs": paragraphs, "cta": cta}

    return None


def _x_max_paragraphs(cta: str) -> int:
    cta_len = len(cta.strip()) if cta else 0
    overhead = 2 + X_URL_LENGTH + (2 + cta_len if cta_len else 0)
    return max(120, X_CHAR_LIMIT - overhead)


def _trim_text(text: str, max_len: int) -> str:
    text = text.strip()
    if len(text) <= max_len:
        return text

    trimmed = text[:max_len]
    punct_idx = max(
        trimmed.rfind("."), trimmed.rfind("!"), trimmed.rfind("?"), trimmed.rfind("\n")
    )
    if punct_idx > int(max_len * 0.5):
        return trimmed[: punct_idx + 1].strip()

    space_idx = trimmed.rfind(" ")
    if space_idx > int(max_len * 0.5):
        return trimmed[:space_idx].strip()

    return trimmed.rstrip()


def _split_sentences(text: str) -> list[str]:
    clean = re.sub(r"\s+", " ", text).strip()
    if not clean:
        return []
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", clean) if s.strip()]


def _build_paragraphs_from_content(content: str, max_len: int, target_min: int) -> str:
    sentences = [s for s in _split_sentences(content) if len(s) >= 35]
    if not sentences:
        return ""

    first = sentences[0]
    second_parts: list[str] = []
    idx = 1

    while idx < len(sentences) and len(" ".join(second_parts)) < 80:
        second_parts.append(sentences[idx])
        idx += 1

    second = (
        " ".join(second_parts)
        if second_parts
        else (sentences[1] if len(sentences) > 1 else "")
    )
    merged = f"{first}\n\n{second}" if second else first

    if len(merged) < target_min and idx < len(sentences):
        merged = f"{merged} {sentences[idx]}".strip()

    return _trim_text(merged, max_len)


def _ensure_two_paragraphs(
    paragraphs: str, content: str, max_len: int, target_min: int
) -> str:
    base = paragraphs.strip()
    if "\n\n" in base and len(base) >= target_min:
        return _trim_text(base, max_len)

    candidate = _build_paragraphs_from_content(content, max_len, target_min)
    if candidate and len(candidate) >= len(base):
        return candidate

    if "\n\n" not in base:
        pieces = _split_sentences(base)
        if len(pieces) >= 2:
            cut = max(1, len(pieces) // 2)
            base = " ".join(pieces[:cut]) + "\n\n" + " ".join(pieces[cut:])

    return _trim_text(base, max_len)


async def summarize_article(article: Article) -> dict:
    content = (
        article.full_content or article.description or article.title or ""
    ).strip()
    if not content:
        logger.error("Empty article content")
        return _fallback_summary(article)

    categories = ", ".join(article.categories[:3]) if article.categories else "-"
    target_max = _x_max_paragraphs("Baca selengkapnya.")
    target_min = max(170, target_max - 35)

    user_prompt = f"""SUMBER: {article.source_name}
JUDUL: {article.title}
KATEGORI: {categories}

PANDUAN OUTPUT:
- paragraphs: 2 paragraf dipisah \n\n.
- target panjang paragraphs: {target_min}-{target_max} karakter.
- cta: 1 kalimat ajakan singkat (8-24 karakter).

ISI ARTIKEL LENGKAP:
{content}

Balas HANYA JSON valid."""

    logger.info("Summarizing article: %s (%s)", article.title, article.source_name)

    try:
        async with httpx.AsyncClient(timeout=90) as client:
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
                    "temperature": 0.6,
                    "max_tokens": 1200,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        ai_response = data["choices"][0]["message"]["content"].strip()
        finish_reason = data["choices"][0].get("finish_reason", "")
        logger.debug("AI raw response (finish=%s): %s", finish_reason, ai_response)

        if finish_reason == "length":
            logger.error("AI response truncated (finish_reason=length), using fallback")
            return _fallback_summary(article)

        result = _extract_json(ai_response)
        if result is None:
            logger.error(
                "Could not extract JSON from AI response: %s", ai_response[:200]
            )
            cta = "Baca selengkapnya."
            paragraphs = _build_paragraphs_from_content(
                content, _x_max_paragraphs(cta), target_min
            )
            if not paragraphs:
                return _fallback_summary(article)
            return {
                "paragraphs": paragraphs,
                "cta": cta,
                "caption": paragraphs,
                "hashtags": [],
                "quote": "",
            }

        paragraphs = str(
            result.get("paragraphs")
            or result.get("body")
            or result.get("caption")
            or ""
        ).strip()
        cta = str(result.get("cta") or "").strip()

        if not paragraphs:
            logger.error("No paragraphs in AI response")
            cta = "Baca selengkapnya."
            paragraphs = _build_paragraphs_from_content(
                content, _x_max_paragraphs(cta), target_min
            )
            if not paragraphs:
                return _fallback_summary(article)

        paragraphs = paragraphs.replace("\r\n", "\n").replace("\r", "\n")
        paragraphs = re.sub(r"\n{3,}", "\n\n", paragraphs)
        paragraphs = re.sub(r"[ \t]+", " ", paragraphs).strip()

        cta = re.sub(r"\s+", " ", cta).strip()
        if not cta:
            cta = "Baca selengkapnya."
        if len(cta) > 24:
            cta = "Baca selengkapnya."

        max_len = _x_max_paragraphs(cta)
        paragraphs = _ensure_two_paragraphs(paragraphs, content, max_len, target_min)

        return {
            "paragraphs": paragraphs,
            "cta": cta,
            "caption": paragraphs,
            "hashtags": [],
            "quote": "",
        }

    except Exception as e:
        logger.error("AI summarization failed: %s", e)
        return _fallback_summary(article)


def _fallback_summary(article: Article) -> dict:
    cta = "Baca selengkapnya."
    raw = (article.description or article.title or "").strip()
    raw = re.sub(r"\s+", " ", raw)
    if not raw:
        raw = "Ringkasan artikel tersedia di link."

    body = _trim_text(raw, _x_max_paragraphs(cta))
    return {
        "paragraphs": body,
        "cta": cta,
        "caption": body,
        "hashtags": [],
        "quote": "",
    }
