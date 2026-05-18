from __future__ import annotations

import html
import hashlib
import hmac
import json
import re
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, quote_plus, unquote_plus, urlparse, urlencode
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .categories import categorize_topic
from .storage import Storage

_MEDIA_CACHE: dict[str, tuple[int, dict[str, Any]]] = {}
_BRIEF_CACHE: dict[str, tuple[int, dict[str, Any]]] = {}
_SESSION_STORE: dict[str, dict[str, Any]] = {}
SOURCE_SCOPE: dict[str, str] = {
    "google_news_se": "sweden",
    "aftonbladet_noje": "sweden",
    "expressen_noje": "sweden",
    "hant": "sweden",
    "hant_extra": "sweden",
    "svenskdam": "sweden",
    "nyheter24_noje": "sweden",
    "svt_noje": "sweden",
    "tv4_noje": "sweden",
    "google_news_global": "global",
    "bbc_entertainment": "global",
    "npr_music": "global",
    "ap_entertainment": "global",
    "variety": "global",
    "billboard": "global",
    "the_verge": "global",
    "people": "global",
    "eonline": "global",
    "tmz": "global",
    "rolling_stone": "global",
    "reddit": "global",
    "tiktok_web": "global",
}
LEADING_NEWS_PHRASES = {"just nu", "senaste", "breaking", "live", "nu"}
SOURCE_ONLY_LABELS = {
    "tv4 nyheterna",
    "tv4",
    "svt nyheter",
    "svt",
    "aftonbladet",
    "expressen",
    "hant",
    "svenskdam",
    "nyheter24",
    "hänt",
    "google news",
    "tiktok",
}


def _render_legal_page(title: str, eyebrow: str, intro: str, sections_html: str) -> str:
    return f"""<!doctype html>
<html lang="sv">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html.escape(title)} - TrendBot</title>
  <style>
    body {{
      margin: 0;
      background: #ebe5de;
      color: #171616;
      font-family: "Avenir Next", "SF Pro Text", "SF Pro Display", Inter, system-ui, -apple-system, sans-serif;
    }}
    .wrap {{ max-width: 1100px; margin: 0 auto; padding: 36px 20px 56px; }}
    .back {{ color: #6a6258; text-decoration: none; font-size: 18px; }}
    .eyebrow {{ margin-top: 10px; color: #d54e1f; font-weight: 800; letter-spacing: .14em; text-transform: uppercase; }}
    h1 {{ margin: 18px 0 12px; font-size: 72px; line-height: .95; letter-spacing: -0.03em; }}
    .intro {{ color: #625b54; font-size: 22px; line-height: 1.5; max-width: 980px; }}
    .card {{
      margin-top: 26px;
      background: #f7f4f0;
      border: 1px solid #ddd2c5;
      border-radius: 28px;
      padding: 28px 28px;
    }}
    h2 {{ margin: 0 0 12px; font-size: 46px; letter-spacing: -0.03em; }}
    h3 {{ margin: 22px 0 8px; font-size: 30px; letter-spacing: -0.02em; }}
    p, li {{ font-size: 18px; line-height: 1.7; color: #625b54; }}
    code {{ background: #efe6db; padding: 2px 8px; border-radius: 8px; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
    th, td {{ border-bottom: 1px solid #ddd2c5; text-align: left; padding: 10px 8px; vertical-align: top; }}
    th {{ color: #2a2119; }}
  </style>
</head>
<body>
  <div class="wrap">
    <a class="back" href="/">Tillbaka till TrendBot</a>
    <div class="eyebrow">{html.escape(eyebrow)}</div>
    <h1>{html.escape(title)}</h1>
    <p class="intro">{html.escape(intro)}</p>
    <div class="card">{sections_html}</div>
  </div>
</body>
</html>"""


def _render_privacy_page() -> str:
    sections = """
      <h2>Integritetspolicy</h2>
      <p>Denna policy gäller TrendBot Dashboard. Vi behandlar personuppgifter enligt GDPR och svensk dataskyddslagstiftning.</p>
      <h3>1. Personuppgiftsansvarig</h3>
      <p><strong>Personuppgiftsansvarig:</strong> TrendBot (ägare av tjänsten).<br />
      <strong>Kontakt:</strong> trendbot.team@gmail.com.</p>
      <h3>2. Vilka uppgifter vi behandlar</h3>
      <ul>
        <li>Inloggningsuppgifter: användarnamn och hash-verifiering av lösenord.</li>
        <li>Tekniska uppgifter: sessionsidentifierare, säkerhetsloggar (inloggningsförsök, fel, missbruksskydd).</li>
        <li>Användarval: tema, watchlist och samtyckesval (lokalt i webbläsaren).</li>
      </ul>
      <h3>3. Ändamål och rättslig grund (GDPR art. 6)</h3>
      <ul>
        <li>Tillhandahålla tjänsten och inloggning: <strong>avtal</strong> (art. 6.1 b).</li>
        <li>Säkerhet, missbruksförebyggande och drift: <strong>berättigat intresse</strong> (art. 6.1 f).</li>
        <li>Icke-nödvändig spårning/analys (om aktiverad): <strong>samtycke</strong> (art. 6.1 a).</li>
      </ul>
      <h3>4. Lagringstid</h3>
      <ul>
        <li>Sessionscookie: upp till 12 timmar, eller tills utloggning.</li>
        <li>Säkerhetsloggar: normalt upp till 90 dagar (kan justeras av driftsskäl).</li>
        <li>Lokala inställningar i webbläsaren: tills användaren raderar dem.</li>
      </ul>
      <h3>5. Mottagare och överföring</h3>
      <p>Data kan behandlas av driftleverantörer (hosting) och tekniska underbiträden. Vi säljer inte personuppgifter. Om tredjelandsöverföring sker ska lämpliga skyddsåtgärder användas.</p>
      <h3>6. Dina rättigheter</h3>
      <ul>
        <li>Rätt till tillgång, rättelse, radering, begränsning, invändning och dataportabilitet.</li>
        <li>Rätt att återkalla samtycke när behandling bygger på samtycke.</li>
        <li>Rätt att klaga till Integritetsskyddsmyndigheten (IMY).</li>
      </ul>
      <h3>7. Kontakt och begäran</h3>
      <p>Skicka begäran till kontaktadressen ovan. Vi svarar normalt inom 30 dagar. Se även <a href="/legal/dsr">rutin för rättighetsbegäran</a>.</p>
    """
    return _render_legal_page(
        "Integritetspolicy",
        "Juridisk information",
        "Här beskriver vi hur personuppgifter behandlas i TrendBot Dashboard.",
        sections,
    )


def _render_cookie_page() -> str:
    sections = """
      <h2>Cookiepolicy</h2>
      <p>Denna sida beskriver cookies och liknande tekniker i TrendBot Dashboard.</p>
      <h3>1. Cookies och lokal lagring som används</h3>
      <table>
        <thead>
          <tr><th>Namn</th><th>Typ</th><th>Syfte</th><th>Varaktighet</th><th>Nödvändig</th></tr>
        </thead>
        <tbody>
          <tr><td><code>trendbot_session</code></td><td>Cookie</td><td>Håller användaren inloggad och skyddar sessionen.</td><td>Upp till 12h / tills utloggning</td><td>Ja</td></tr>
          <tr><td><code>trendbot_theme_v1</code></td><td>localStorage</td><td>Sparar valt tema (light/dark).</td><td>Tills borttagning</td><td>Nej (funktionell)</td></tr>
          <tr><td><code>trendbot_watchlist_v1</code></td><td>localStorage</td><td>Sparar lokal watchlist i webbläsaren.</td><td>Tills borttagning</td><td>Nej (funktionell)</td></tr>
          <tr><td><code>trendbot_cookie_consent_v1</code></td><td>localStorage</td><td>Sparar samtyckesval för icke-nödvändig spårning.</td><td>Tills borttagning / 12 månader rekommenderat</td><td>Ja (för att minnas val)</td></tr>
        </tbody>
      </table>
      <h3>2. Tredje part</h3>
      <p>När du klickar utgående länkar (t.ex. Google-sökning, nyhetssajter, sociala plattformar) kan tredje part sätta egna cookies enligt sina policyer.</p>
      <h3>3. Samtycke för icke-nödvändiga cookies</h3>
      <p>Om analys/annonsering/pixels aktiveras visas samtyckesruta innan sådana tekniker används. Utan samtycke ska de inte laddas.</p>
      <h3>4. Hur du återkallar samtycke</h3>
      <ul>
        <li>Rensa webbplatsdata i din webbläsare, eller</li>
        <li>ta bort <code>trendbot_cookie_consent_v1</code> i localStorage, eller</li>
        <li>kontakta supporten för hjälp.</li>
      </ul>
    """
    return _render_legal_page(
        "Cookiepolicy",
        "Juridisk information",
        "Här beskriver vi vilka cookies och liknande tekniker som används på webbplatsen och varför.",
        sections,
    )


def _render_dsr_page() -> str:
    sections = """
      <h2>Rutin för rättighetsbegäran</h2>
      <ol>
        <li>Ta emot begäran via dedikerad e-post (trendbot.team@gmail.com).</li>
        <li>Verifiera identitet på ett proportionerligt sätt.</li>
        <li>Registrera ärendet i intern logg med datum, typ av begäran och ansvarig.</li>
        <li>Bedöm rättslig grund och eventuella undantag.</li>
        <li>Svara utan onödigt dröjsmål, normalt inom 30 dagar.</li>
        <li>Dokumentera utfall och åtgärd.</li>
      </ol>
      <p>Denna rutin ska finnas operativt och följas i praktiken, inte bara beskrivas i policytext.</p>
      <p>Se även <a href="/legal/register">register över behandling (mall)</a>.</p>
    """
    return _render_legal_page(
        "Rättighetsbegäran",
        "GDPR-process",
        "Intern och extern process för hantering av registrerades rättigheter.",
        sections,
    )


def _render_register_page() -> str:
    sections = """
      <h2>Register över behandling (RoPA)</h2>
      <p>Använd denna mall internt och håll den uppdaterad.</p>
      <table>
        <thead>
          <tr><th>Behandling</th><th>Ändamål</th><th>Kategori data</th><th>Rättslig grund</th><th>Mottagare</th><th>Lagring</th><th>Säkerhet</th></tr>
        </thead>
        <tbody>
          <tr><td>Inloggning</td><td>Åtkomstkontroll</td><td>Användarnamn, sessions-id</td><td>Avtal / berättigat intresse</td><td>Hosting-leverantör</td><td>Session + loggar</td><td>Hashade lösenord, rate-limit</td></tr>
          <tr><td>Säkerhetsloggar</td><td>Missbruksskydd</td><td>Teknisk loggdata</td><td>Berättigat intresse</td><td>Hosting-leverantör</td><td>90 dagar (riktlinje)</td><td>Åtkomststyrning</td></tr>
          <tr><td>Samtycke</td><td>Minnas val</td><td>Samtyckesstatus</td><td>Rättslig skyldighet/berättigat intresse</td><td>Ingen extern delning</td><td>Tills radering</td><td>Lokal lagring</td></tr>
        </tbody>
      </table>
    """
    return _render_legal_page(
        "Register över behandling",
        "GDPR-dokumentation",
        "Detta är en publik mall. Behåll även en intern, detaljerad version.",
        sections,
    )


def _format_ts(value: int) -> str:
    if not value:
        return "-"
    from datetime import datetime, timezone

    stockholm = ZoneInfo("Europe/Stockholm")
    return datetime.fromtimestamp(value, tz=timezone.utc).astimezone(stockholm).strftime("%Y-%m-%d %H:%M %Z")


GENERIC_SERIES_LABELS = {
    "news",
    "music",
    "movies",
    "movie",
    "tv",
    "television",
    "politics",
    "pop culture",
    "celebrity",
    "fashion",
    "sports",
    "streaming",
    "podcasts",
    "gaming",
    "internet culture",
    "viral video",
    "influencer",
    "youtube",
    "k-pop",
    "eurovision",
}
MONTH_WORDS = {
    "jan", "january", "feb", "february", "mar", "march", "apr", "april", "may",
    "jun", "june", "jul", "july", "aug", "august", "sep", "sept", "september",
    "oct", "october", "nov", "november", "dec", "december",
}

POSITIVE_REACTION_WORDS = {
    "älskar", "hyllar", "wow", "iconic", "queen", "king", "bäst", "magisk",
    "amazing", "love", "great", "epic", "starkt", "snyggt", "briljant",
}
NEGATIVE_REACTION_WORDS = {
    "rasar", "chock", "skandal", "bråk", "kritik", "hate", "outrage", "drama",
    "backlash", "controversy", "cancel", "anklag", "kaos", "storm", "scandal",
}
STRONG_REACTION_WORDS = {
    "chock", "skandal", "bråk", "rasar", "ilska", "drama", "storm", "outrage",
    "backlash", "controversy", "kaos", "anklag", "läckt", "avslöjar",
}


def _strip_leading_news_phrase(text: str) -> str:
    value = (text or "").strip()
    if not value:
        return ""
    return re.sub(r"^(just nu|senaste|breaking|live|nu)\s*[:\-–—]?\s*", "", value, flags=re.IGNORECASE).strip()


def _is_leading_news_phrase(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", (text or "").lower().strip())
    return normalized in LEADING_NEWS_PHRASES


def _is_source_only_label(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", (text or "").lower().strip())
    return normalized in SOURCE_ONLY_LABELS


def _clean_example_title(title: str) -> str:
    cleaned = (title or "").strip()
    if not cleaned:
        return ""
    cleaned = _strip_leading_news_phrase(cleaned)
    if " - " in cleaned:
        left, right = cleaned.split(" - ", 1)
        left = _strip_leading_news_phrase(left)
        left_norm = re.sub(r"\s+", " ", left.lower().strip())
        if not left or left_norm in GENERIC_SERIES_LABELS:
            cleaned = right.strip()
        else:
            cleaned = left.strip()
    if "|" in cleaned:
        cleaned = cleaned.split("|", 1)[0].strip()
    if ":" in cleaned:
        prefix, suffix = cleaned.split(":", 1)
        if len(prefix.strip()) <= 18 and suffix.strip():
            cleaned = suffix.strip()
    cleaned = _strip_leading_news_phrase(cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _looks_dateish(text: str) -> bool:
    value = re.sub(r"\s+", " ", (text or "").lower().strip())
    if not value:
        return True
    if re.fullmatch(r"\d{1,2}(\s*[/-]\s*\d{1,2})?(\s*[/-]\s*\d{2,4})?", value):
        return True
    parts = value.split()
    if len(parts) <= 3 and any(part in MONTH_WORDS for part in parts):
        return True
    return False


def _is_genericish_label(text: str) -> bool:
    tokens = [tok for tok in re.findall(r"[a-z0-9]+", (text or "").lower()) if tok]
    if not tokens:
        return True
    generic_hits = 0
    for tok in tokens:
        if tok in {
            "movies", "movie", "tv", "shows", "show", "series", "music", "news",
            "celebrity", "pop", "culture", "viral", "video", "videos", "internet",
        }:
            generic_hits += 1
    return generic_hits >= max(2, int(len(tokens) * 0.6))


def _series_label(cluster_label: str, example_title: str) -> str:
    label = (cluster_label or "").strip()
    normalized = " ".join(label.lower().split())
    if (
        label
        and normalized not in GENERIC_SERIES_LABELS
        and len(label.split()) >= 2
        and not _looks_dateish(label)
        and not _is_genericish_label(label)
        and not _is_leading_news_phrase(label)
        and not _is_source_only_label(label)
    ):
        return label
    fallback = _clean_example_title(example_title)
    fallback_norm = " ".join(fallback.lower().split())
    if (
        fallback
        and fallback_norm not in GENERIC_SERIES_LABELS
        and not _looks_dateish(fallback)
        and not _is_genericish_label(fallback)
        and not _is_leading_news_phrase(fallback)
        and not _is_source_only_label(fallback)
    ):
        return fallback
    raw_example = (example_title or "").strip()
    if "|" in raw_example:
        raw_example = raw_example.split("|", 1)[0].strip()
    if " - " in raw_example:
        raw_example = raw_example.split(" - ", 1)[0].strip()
    raw_example = re.sub(r"\s+", " ", raw_example).strip()
    raw_norm = " ".join(raw_example.lower().split())
    if (
        raw_example
        and len(raw_example.split()) >= 2
        and raw_norm not in GENERIC_SERIES_LABELS
        and not _looks_dateish(raw_example)
        and not _is_genericish_label(raw_example)
        and not _is_leading_news_phrase(raw_example)
        and not _is_source_only_label(raw_example)
    ):
        return raw_example
    if (
        label
        and not _looks_dateish(label)
        and not _is_leading_news_phrase(label)
        and not _is_source_only_label(label)
    ):
        return label
    return ""


def _is_context_label(text: str) -> bool:
    value = (text or "").strip()
    if not value:
        return False
    if _looks_dateish(value):
        return False
    if _is_genericish_label(value):
        return False
    if _is_leading_news_phrase(value):
        return False
    if _is_source_only_label(value):
        return False
    if " ".join(value.lower().split()) in GENERIC_SERIES_LABELS:
        return False
    return len(value.split()) >= 2


def _label_specificity_score(text: str) -> int:
    value = re.sub(r"\s+", " ", (text or "").strip())
    if not value:
        return -1
    tokens = re.findall(r"[A-Za-zÅÄÖåäö0-9]+", value)
    if not tokens:
        return -1
    unique_tokens = len(set(tok.lower() for tok in tokens))
    digits = sum(1 for tok in tokens if any(ch.isdigit() for ch in tok))
    long_tokens = sum(1 for tok in tokens if len(tok) >= 6)
    return (unique_tokens * 3) + (digits * 2) + long_tokens


def _is_vague_label(text: str) -> bool:
    value = re.sub(r"\s+", " ", (text or "").lower().strip())
    if not value:
        return True
    vague_phrases = {
        "frågetecknen kvar",
        "oklart läge",
        "fortsatt oklart",
        "mer detaljer väntas",
        "utveckling pågår",
        "rubrik saknar kontext",
    }
    if value in vague_phrases:
        return True
    return len(value.split()) <= 2 and any(word in value for word in ("kvar", "oklart", "pågår"))


def _expand_with_example_context(label: str, example_title: str) -> str:
    if not _is_vague_label(label):
        return label
    raw = (example_title or "").strip()
    if not raw:
        return label
    parts = [part.strip() for part in re.split(r"\s[-–—]\s", raw) if part.strip()]
    # Prefer the most descriptive non-source segment from the example title.
    candidates = []
    for part in parts:
        cleaned = _strip_leading_news_phrase(part)
        if _is_source_only_label(cleaned):
            continue
        if not _looks_dateish(cleaned):
            candidates.append(cleaned)
    for cand in candidates:
        if len(cand.split()) >= 3:
            return cand
    for cand in candidates:
        if len(cand.split()) >= 2:
            return cand
    return label


def _topic_reaction(topic: str, example_title: str, total_mentions: int, source_count: int) -> dict[str, Any]:
    text = f"{topic} {example_title}".lower()
    positive = sum(1 for w in POSITIVE_REACTION_WORDS if w in text)
    negative = sum(1 for w in NEGATIVE_REACTION_WORDS if w in text)
    strong = sum(1 for w in STRONG_REACTION_WORDS if w in text)
    punctuation_signal = text.count("!") + text.count("?")
    sentiment_score = max(-100, min(100, (positive - negative) * 18))
    if sentiment_score > 12:
        mood = "Mest positiv"
    elif sentiment_score < -12:
        mood = "Mest negativ"
    else:
        mood = "Blandad reaktion"
    volume_bonus = min(35, max(0, int(total_mentions) * 2))
    source_bonus = min(20, max(0, int(source_count) * 4))
    language_signal = (strong * 20) + (negative * 8) + (positive * 6) + (punctuation_signal * 3)
    intensity = min(100, max(8, language_signal + volume_bonus + source_bonus))
    return {
        "mood": mood,
        "sentiment_score": sentiment_score,
        "intensity": intensity,
    }


def _summary_payload(storage: Storage, settings: dict[str, Any], market_scope: str | None = None) -> dict[str, Any]:
    from datetime import datetime, timezone

    blocked_terms = [str(t).strip().lower() for t in (settings.get("blocked_terms") or []) if str(t).strip()]

    def _is_blocked(*values: str) -> bool:
        if not blocked_terms:
            return False
        text = " ".join((value or "") for value in values).lower()
        return any(term in text for term in blocked_terms)

    def _is_swedish_story(*values: str) -> bool:
        text = " ".join((value or "") for value in values).lower()
        swedish_markers = (
            "tv4", "svt", "aftonbladet", "expressen", "hänt", "hant", "nyheterna",
            "sverige", "svensk", "uppsala", "stockholm", "göteborg", "malmö",
            "mello", "melodifestivalen",
        )
        if any(marker in text for marker in swedish_markers):
            return True
        # Heuristic: Swedish chars usually indicate Swedish-local headline context.
        return any(ch in text for ch in ("å", "ä", "ö"))

    now = int(datetime.now(tz=timezone.utc).timestamp())
    min_daily_mentions = int(settings.get("daily_top_min_mentions", 3))

    def _apply_scope(rows):
        if market_scope == "global":
            return [
                row
                for row in rows
                if not _is_swedish_story(row.topic, row.cluster_label, row.example_title)
            ]
        if market_scope == "sweden":
            return [
                row
                for row in rows
                if _is_swedish_story(row.topic, row.cluster_label, row.example_title)
            ]
        return rows

    def _topics_for_window(window_seconds: int, limit: int, min_total_mentions: int):
        rows = storage.top_topics_since(
            now - window_seconds,
            limit,
            min_total_mentions=min_total_mentions,
            market_scope=market_scope,
        )
        rows = [
            row
            for row in rows
            if not _is_blocked(row.topic, row.cluster_label, row.example_title)
        ]
        return _apply_scope(rows)

    def _clusters_for_window(window_seconds: int, limit: int):
        rows = storage.top_clusters_since(now - window_seconds, limit, market_scope=market_scope)
        rows = [row for row in rows if not _is_blocked(row.cluster_label, row.example_title)]
        if market_scope == "global":
            rows = [row for row in rows if not _is_swedish_story(row.cluster_label, row.example_title)]
        elif market_scope == "sweden":
            rows = [row for row in rows if _is_swedish_story(row.cluster_label, row.example_title)]
        return rows

    top_topic_candidates = _topics_for_window(86400, 80, min_daily_mentions)
    hot_topics = _topics_for_window(3600, 40, 1)[:10]
    lookback_used_seconds = 86400
    data_mode = "live_24h"

    # If the bot was down, avoid blank/zero UI by falling back to the latest known window.
    if not top_topic_candidates:
        for fallback_window_seconds in (86400 * 3, 86400 * 7, 86400 * 30):
            fallback_topics = _topics_for_window(
                fallback_window_seconds,
                80,
                max(1, min_daily_mentions - 1),
            )
            if fallback_topics:
                top_topic_candidates = fallback_topics
                lookback_used_seconds = fallback_window_seconds
                data_mode = f"fallback_{fallback_window_seconds // 86400}d"
                break

    if not hot_topics:
        if lookback_used_seconds > 3600:
            hot_topics = _topics_for_window(lookback_used_seconds, 40, 1)[:10]
        if not hot_topics and top_topic_candidates:
            hot_topics = top_topic_candidates[:10]
    # Merge daily + hot so fresh stories can enter without wiping the whole ranking.
    merged_candidates: dict[str, Any] = {}
    for item in list(top_topic_candidates) + list(hot_topics):
        if not item.cluster_key:
            continue
        current = merged_candidates.get(item.cluster_key)
        if current is None:
            merged_candidates[item.cluster_key] = item
            continue
        # Prefer stronger signal, then recency.
        current_score = (current.total_mentions, current.latest_observed_at, current.trend_score)
        new_score = (item.total_mentions, item.latest_observed_at, item.trend_score)
        if new_score > current_score:
            merged_candidates[item.cluster_key] = item
    top_topic_candidates = list(merged_candidates.values())

    sticky_key = "dashboard:sticky_top10:v2"
    previous_raw = storage.get_state(sticky_key)
    previous_keys: list[str] = []
    if previous_raw:
        try:
            parsed = json.loads(previous_raw)
            if isinstance(parsed, list):
                previous_keys = [str(item) for item in parsed if str(item)]
        except json.JSONDecodeError:
            previous_keys = []
    previous_rank = {key: idx for idx, key in enumerate(previous_keys)}

    candidates_by_key = {item.cluster_key: item for item in top_topic_candidates if item.cluster_key}
    max_mentions = max((item.total_mentions for item in top_topic_candidates), default=0)
    retain_floor = max(2, int(max_mentions * 0.25)) if max_mentions > 0 else 2

    # Keep previous ranked topics unless they become clearly weak.
    sticky_topics: list[Any] = []
    for key in previous_keys:
        item = candidates_by_key.get(key)
        if not item:
            continue
        if item.total_mentions >= retain_floor:
            sticky_topics.append(item)

    # Fill with strongest remaining candidates.
    used_keys = {item.cluster_key for item in sticky_topics}
    remaining = [item for item in top_topic_candidates if item.cluster_key not in used_keys]
    remaining.sort(key=lambda item: (item.total_mentions, item.latest_observed_at, item.trend_score), reverse=True)
    top_topics = (sticky_topics + remaining)[:10]

    # If we still have fewer than 10, backfill with the strongest daily candidates.
    if len(top_topics) < 10:
        already = {item.cluster_key for item in top_topics}
        backfill = [item for item in _topics_for_window(86400 * 3, 120, max(1, min_daily_mentions - 1)) if item.cluster_key not in already]
        backfill.sort(key=lambda item: (item.total_mentions, item.latest_observed_at, item.trend_score), reverse=True)
        top_topics.extend(backfill[: 10 - len(top_topics)])
    storage.set_state(sticky_key, json.dumps([item.cluster_key for item in top_topics]))
    top_categories = storage.top_categories_since(
        now - lookback_used_seconds,
        8,
        market_scope=market_scope,
    )
    top_clusters = _clusters_for_window(lookback_used_seconds, 30)[:10]
    featured_topic = top_topics[0].topic if top_topics else ""
    featured_cluster = top_clusters[0].cluster_key if top_clusters else ""
    category_multipliers = {
        "pop_culture": (
            float(settings.get("pop_culture_spike_multiplier", 2.0)),
            int(settings.get("pop_culture_min_baseline", 1)),
        ),
        "default": (
            float(settings.get("spike_multiplier", 2.5)),
            int(settings.get("min_baseline", 2)),
        ),
    }
    backtest = storage.backtest_summary(
        now - 86400 * 7,
        int(settings.get("window_size", 12)),
        category_multipliers,
    )
    alert_count_offset = int(settings.get("alert_count_offset", 0))
    live_alerts_24h = storage.count_alert_events_since(now - 86400) + alert_count_offset
    live_alerts_7d = storage.count_alert_events_since(now - 86400 * 7) + alert_count_offset
    daily_series_bucket_seconds = int(settings.get("daily_series_bucket_seconds", 180))
    daily_series_window_seconds = int(settings.get("daily_series_window_seconds", 21600))
    daily_series_since = now - daily_series_window_seconds
    featured_series = (
        storage.cluster_timeseries(
            featured_cluster,
            now - 86400,
            bucket_seconds=daily_series_bucket_seconds,
            until_ts=now,
        )
        if featured_cluster
        else []
    )
    cluster_series = (
        storage.cluster_timeseries(
            featured_cluster,
            daily_series_since,
            bucket_seconds=daily_series_bucket_seconds,
            until_ts=now,
        )
        if featured_cluster
        else []
    )
    cluster_multi_series_all = []
    for cluster in top_clusters:
        display_label = _series_label(cluster.cluster_label, cluster.example_title)
        series_points = storage.cluster_timeseries(
            cluster.cluster_key,
            daily_series_since,
            bucket_seconds=daily_series_bucket_seconds,
            until_ts=now,
        )
        cluster_multi_series_all.append(
            {
                "cluster_key": cluster.cluster_key,
                "cluster_label": display_label,
                "category": cluster.category,
                "series": [
                    {
                        "bucket_ts": point.bucket_ts,
                        "total_mentions": point.total_mentions,
                        "trend_score": point.trend_score,
                        "label": _format_ts(point.bucket_ts),
                    }
                    for point in series_points
                ],
            }
        )
    cluster_multi_series = cluster_multi_series_all[:5]

    candidate_labels_by_cluster: dict[str, list[tuple[str, str]]] = {}
    for row in list(top_topics) + list(hot_topics):
        key = row.cluster_key or ""
        if not key:
            continue
        candidates = candidate_labels_by_cluster.setdefault(key, [])
        for cand in (
            _series_label(row.cluster_label, row.example_title),
            _clean_example_title(row.example_title),
            _strip_leading_news_phrase(row.topic or ""),
        ):
            pair = (cand, row.example_title or "")
            if cand and pair not in candidates:
                candidates.append(pair)

    def _best_cluster_label(cluster_key: str, fallback_label: str, fallback_example: str, fallback_topic: str = "") -> str:
        valid_candidates: list[str] = []

        base = _series_label(fallback_label, fallback_example)
        if base:
            expanded = _expand_with_example_context(base, fallback_example)
            if _is_context_label(expanded) and not _is_vague_label(expanded):
                valid_candidates.append(expanded)

        for cand, cand_example in candidate_labels_by_cluster.get(cluster_key or "", []):
            if _is_context_label(cand):
                expanded = _expand_with_example_context(cand, cand_example or fallback_example)
                if _is_context_label(expanded) and not _is_vague_label(expanded):
                    valid_candidates.append(expanded)

        topic_guess = _strip_leading_news_phrase(fallback_topic or "")
        if _is_context_label(topic_guess):
            expanded = _expand_with_example_context(topic_guess, fallback_example)
            if _is_context_label(expanded) and not _is_vague_label(expanded):
                valid_candidates.append(expanded)

        if valid_candidates:
            return max(valid_candidates, key=_label_specificity_score)

        if _is_context_label(base):
            return base
        expanded_base = _expand_with_example_context(base or "", fallback_example)
        if _is_context_label(expanded_base):
            return expanded_base
        # Last-resort fallback: clean something human-readable instead of generic placeholder text.
        fallback = _clean_example_title(fallback_example) or _strip_leading_news_phrase(fallback_topic or "")
        if not fallback:
            fallback = re.sub(r"^cluster:\s*", "", cluster_key or "", flags=re.IGNORECASE).replace("_", " ").strip()
        fallback = re.sub(r"\s+", " ", fallback).strip(" -–—:")
        return fallback or "Oklart ämne"

    latest_known_observed_at = 0
    if top_topics:
        latest_known_observed_at = max(latest_known_observed_at, max(row.latest_observed_at for row in top_topics))
    if hot_topics:
        latest_known_observed_at = max(latest_known_observed_at, max(row.latest_observed_at for row in hot_topics))

    return {
        "top_topics": [
            {
                "topic": _best_cluster_label(row.cluster_key, row.cluster_label, row.example_title, row.topic),
                "cluster_key": row.cluster_key,
                "example_title": row.example_title,
                "total_mentions": row.total_mentions,
                "samples": row.samples,
                "latest_observed_at": row.latest_observed_at,
                "latest_observed_at_human": _format_ts(row.latest_observed_at),
                "latest_published_at": row.latest_published_at,
                "latest_published_at_human": _format_ts(row.latest_published_at),
                "trend_score": row.trend_score,
                "category": row.category,
                "cluster_label": row.cluster_label,
                "source_count": row.source_count,
                "link": f"https://www.google.com/search?q={quote_plus(_best_cluster_label(row.cluster_key, row.cluster_label, row.example_title, row.topic))}",
            }
            for row in top_topics
        ],
        "hot_topics": [
            {
                "topic": _best_cluster_label(row.cluster_key, row.cluster_label, row.example_title, row.topic),
                "cluster_key": row.cluster_key,
                "example_title": row.example_title,
                "total_mentions": row.total_mentions,
                "samples": row.samples,
                "latest_observed_at": row.latest_observed_at,
                "latest_observed_at_human": _format_ts(row.latest_observed_at),
                "latest_published_at": row.latest_published_at,
                "latest_published_at_human": _format_ts(row.latest_published_at),
                "trend_score": row.trend_score,
                "category": row.category,
                "cluster_label": row.cluster_label,
                "source_count": row.source_count,
                "link": f"https://www.google.com/search?q={quote_plus(_best_cluster_label(row.cluster_key, row.cluster_label, row.example_title, row.topic))}",
            }
            for row in hot_topics
        ],
        "reaction_topics": [
            {
                "topic": row.topic,
                "display_topic": _best_cluster_label(row.cluster_key, row.cluster_label, row.example_title, row.topic),
                "category": row.category,
                "example_title": row.example_title,
                **_topic_reaction(
                    _best_cluster_label(row.cluster_key, row.cluster_label, row.example_title, row.topic),
                    row.example_title,
                    row.total_mentions,
                    row.source_count,
                ),
            }
            for row in top_topics[:8]
        ],
        "category_movers": [
            {
                "category": row.category,
                "total_mentions": row.total_mentions,
                "samples": row.samples,
                "latest_observed_at": row.latest_observed_at,
                "top_topic": row.top_topic,
                "trend_score": row.trend_score,
            }
            for row in top_categories
        ],
        "top_clusters": [
            {
                "cluster_key": row.cluster_key,
                "cluster_label": _best_cluster_label(row.cluster_key, row.cluster_label, row.example_title),
                "category": row.category,
                "total_mentions": row.total_mentions,
                "samples": row.samples,
                "latest_observed_at": row.latest_observed_at,
                "latest_published_at": row.latest_published_at,
                "topic_count": row.topic_count,
                "trend_score": row.trend_score,
                "example_title": row.example_title,
            }
            for row in top_clusters
        ],
        "featured_label": (
            _best_cluster_label(top_clusters[0].cluster_key, top_clusters[0].cluster_label, top_clusters[0].example_title)
            if top_clusters
            else (featured_topic or "No featured topic yet.")
        ),
        "featured_series": [
            {
                "bucket_ts": point.bucket_ts,
                "total_mentions": point.total_mentions,
                "trend_score": point.trend_score,
                "label": _format_ts(point.bucket_ts),
            }
            for point in featured_series
        ],
        "cluster_label": (
            _best_cluster_label(top_clusters[0].cluster_key, top_clusters[0].cluster_label, top_clusters[0].example_title)
            if top_clusters
            else "No cluster yet."
        ),
        "cluster_series": [
            {
                "bucket_ts": point.bucket_ts,
                "total_mentions": point.total_mentions,
                "trend_score": point.trend_score,
                "label": _format_ts(point.bucket_ts),
            }
            for point in cluster_series
        ],
        "cluster_multi_series": cluster_multi_series,
        "cluster_multi_series_all": cluster_multi_series_all,
        "backtest": {
            "lookback_days": backtest.lookback_days,
            "simulated_alerts": backtest.simulated_alerts,
            "topics_tested": backtest.topics_tested,
            "alert_rate": backtest.alert_rate,
            "strongest_topic": backtest.strongest_topic,
            "strongest_category": backtest.strongest_category,
            "strongest_score": backtest.strongest_score,
            "live_alerts_24h": live_alerts_24h,
            "live_alerts_7d": live_alerts_7d,
        },
        "market_scope": market_scope or "all",
        "data_mode": data_mode,
        "lookback_used_seconds": lookback_used_seconds,
        "latest_known_observed_at": latest_known_observed_at,
        "latest_known_observed_at_human": _format_ts(latest_known_observed_at) if latest_known_observed_at else "",
    }


def _recent_payload(storage: Storage, market_scope: str | None = None) -> dict[str, Any]:
    items = storage.recent_observations_global(20)
    if market_scope in {"sweden", "global"}:
        items = [item for item in items if SOURCE_SCOPE.get(item.source, "global") == market_scope]
    if not items:
        # Fallback to latest known rows so reload never looks completely dead.
        items = storage.recent_observations_global(20)
    payload = []
    total_new = 0
    total_fetched = 0
    for row in items:
        total_new += int(row.new_mentions)
        total_fetched += int(row.fetched_mentions)
        payload.append(
            {
                "topic": row.topic,
                "source": row.source,
                "observed_at": row.observed_at,
                "observed_at_human": _format_ts(row.observed_at),
                "new_mentions": row.new_mentions,
                "fetched_mentions": row.fetched_mentions,
                "category": categorize_topic(row.topic),
            }
        )
    return {
        "items": payload,
        "total_new_mentions": total_new,
        "total_fetched_mentions": total_fetched,
    }


def _extract_img_src(fragment: str) -> str:
    if not fragment:
        return ""
    match = re.search(r'<img[^>]+src="([^"]+)"', fragment, flags=re.IGNORECASE)
    if not match:
        return ""
    return html.unescape(match.group(1)).strip()


def _strip_html(fragment: str) -> str:
    if not fragment:
        return ""
    return html.unescape(re.sub(r"<[^>]+>", " ", fragment)).strip()


def _extract_og_image(url: str) -> str:
    if not url:
        return ""
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 trendbot/0.1",
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            payload = response.read(250_000).decode("utf-8", errors="ignore")
    except Exception:
        return ""
    patterns = [
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
        r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image["\']',
    ]
    for pattern in patterns:
        match = re.search(pattern, payload, flags=re.IGNORECASE)
        if match:
            return html.unescape(match.group(1)).strip()
    return ""


def _google_placeholder_thumb(text: str) -> str:
    label = (text or "Google topic").strip()[:42]
    svg = f"""
<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 640 480'>
  <defs>
    <linearGradient id='g' x1='0' x2='1' y1='0' y2='1'>
      <stop offset='0%' stop-color='#1a73e8'/>
      <stop offset='100%' stop-color='#34a853'/>
    </linearGradient>
  </defs>
  <rect width='640' height='480' fill='url(#g)'/>
  <circle cx='86' cy='86' r='44' fill='#ea4335'/>
  <circle cx='154' cy='86' r='44' fill='#fbbc05'/>
  <circle cx='120' cy='158' r='44' fill='#1a73e8'/>
  <text x='32' y='248' fill='white' font-size='38' font-family='Arial, sans-serif'>Google Trend</text>
  <text x='32' y='302' fill='white' font-size='28' font-family='Arial, sans-serif'>{html.escape(label)}</text>
</svg>
"""
    return "data:image/svg+xml;charset=UTF-8," + quote(svg)


def _google_news_media(topic: str, limit: int = 12) -> list[dict[str, str]]:
    if not topic:
        return []
    url = (
        "https://news.google.com/rss/search?"
        + urlencode(
            {
                "q": topic,
                "hl": "en-US",
                "gl": "US",
                "ceid": "US:en",
            }
        )
    )
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 trendbot/0.1",
            "Accept": "application/xml,text/xml;q=0.9,*/*;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            payload = response.read()
    except Exception:
        return []
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        return []

    channel = root.find("channel")
    if channel is None:
        return []

    items: list[dict[str, str]] = []
    for entry in channel.findall("item")[: max(1, limit)]:
        title = html.unescape((entry.findtext("title", default="") or "").strip())
        link = html.unescape((entry.findtext("link", default="") or "").strip())
        description = entry.findtext("description", default="") or ""
        thumb = _extract_img_src(description)
        if not thumb and link:
            thumb = _extract_og_image(link)
        text_fallback = _strip_html(description)
        if not title:
            continue
        if not thumb:
            thumb = _google_placeholder_thumb(title)
        items.append(
            {
                "title": title,
                "url": link or f"https://news.google.com/search?q={quote_plus(topic)}",
                "thumbnail": thumb,
                "summary": text_fallback[:220],
            }
        )
    return items


def _fallback_images(topic: str, limit: int = 12) -> list[dict[str, str]]:
    fallback: list[dict[str, str]] = []
    for idx in range(min(limit, 12)):
        src = f"https://source.unsplash.com/featured/640x480/?{quote_plus(topic)}&sig={idx}"
        fallback.append(
            {
                "title": topic,
                "url": src,
                "thumbnail": src,
                "full_image": src,
            }
        )
    return fallback


def _media_payload(topic: str) -> dict[str, Any]:
    clean_topic = unquote_plus((topic or "").strip())
    cache_key = clean_topic.lower()
    now = int(time.time())
    cached = _MEDIA_CACHE.get(cache_key)
    if cached and (now - cached[0]) < 600:
        return cached[1]
    images = _google_news_media(clean_topic, limit=18)
    videos = _google_news_media(f"{clean_topic} video", limit=12)
    if not videos:
        videos = _google_news_media(clean_topic, limit=12)
    if not images:
        images = _fallback_images(clean_topic, limit=12)
    payload = {
        "topic": clean_topic,
        "images": images,
        "videos": videos,
    }
    _MEDIA_CACHE[cache_key] = (now, payload)
    return payload


def _clean_source_tail(text: str) -> str:
    cleaned = (text or "").strip()
    if not cleaned:
        return ""
    cleaned = re.sub(
        r"\s[-–—]\s(?:Aftonbladet|Expressen|SVT(?: Nyheter)?|TV4(?: Nyheterna)?|Omni|Reuters|AP News|BBC|People\.com|Billboard|Variety|The Verge|Yahoo|Fox \d+|[A-ZÅÄÖ]{2,6}|[A-Za-z0-9.-]+\.(?:se|com|org|net))$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def _first_sentence(text: str) -> str:
    value = _strip_html(text or "")
    value = re.sub(r"\s+", " ", value).strip()
    if not value:
        return ""
    parts = re.split(r"(?<=[.!?])\s+", value)
    if not parts:
        return value[:180]
    return parts[0][:220].strip()


def _infer_reason(texts: list[str]) -> str:
    connectors = ["efter", "när", "sedan", "i samband med", "på grund av", "därför att"]
    for text in texts:
        low = text.lower()
        for connector in connectors:
            idx = low.find(f"{connector} ")
            if idx >= 0:
                phrase = text[idx:].strip(" .,:;-")
                if len(phrase) >= 16:
                    return phrase[:170]
    for text in texts:
        low = text.lower()
        if any(word in low for word in ["kritik", "anklag", "bråk", "konflikt", "avhopp", "avslöj", "polis", "utred"]):
            return text[:170]
    return ""


def _ensure_period(text: str) -> str:
    value = (text or "").strip()
    if not value:
        return ""
    if value[-1] in ".!?":
        return value
    return value + "."


def _event_from_headline(headline: str, topic: str) -> str:
    clean = _clean_source_tail(headline)
    if not clean:
        return f"Nya uppgifter har kommit om {topic}"
    parts = re.split(r"\s[–—-]\s", clean, maxsplit=1)
    if len(parts) == 2:
        left = _ensure_period(parts[0])
        right = _ensure_period(parts[1][:1].upper() + parts[1][1:] if parts[1] else "")
        if left and right:
            return f"{left} {right}"
    return _ensure_period(clean)


def _impact_sentence(topic: str) -> str:
    lower = (topic or "").lower()
    if any(word in lower for word in ["tv", "reality", "förrädarna", "paradise", "ex on the beach", "love island", "idol", "lets dance"]):
        return "Det som avgör fortsättningen nu är om kanalen eller deltagarna bekräftar fler detaljer i nästa uppdatering."
    if any(word in lower for word in ["tiktok", "influencer", "youtub", "streamer", "internet"]):
        return "Nästa steg blir att se om fler profiler kommenterar och om uppgifterna får officiell bekräftelse."
    return "Nästa steg är att följa nästa bekräftade besked från huvudpersonerna eller ansvarig kanal."


def _topic_brief_payload(topic: str) -> dict[str, Any]:
    clean_topic = unquote_plus((topic or "").strip())
    cache_key = clean_topic.lower()
    now = int(time.time())
    cached = _BRIEF_CACHE.get(cache_key)
    if cached and (now - cached[0]) < 600:
        return cached[1]

    rows = _google_news_media(clean_topic, limit=8)
    titles = [_clean_source_tail((row.get("title") or "").strip()) for row in rows if (row.get("title") or "").strip()]
    summaries = [_first_sentence(row.get("summary") or "") for row in rows]
    titles = [t for t in titles if t]
    summaries = [s for s in summaries if s]

    headline = titles[0] if titles else f"Nya uppgifter om {clean_topic}"
    event_sentence = _event_from_headline(headline, clean_topic)
    reason_phrase = _infer_reason(summaries + titles)
    if reason_phrase:
        reason_sentence = _ensure_period(f"Det som uppges just nu är {reason_phrase}")
    elif summaries:
        reason_sentence = _ensure_period(f"Det som framgår i första rapporteringen är: {summaries[0].rstrip('.')}")
    else:
        reason_sentence = "Det finns ännu ingen tydlig bekräftad orsak i öppna källor."

    follow_up = _impact_sentence(clean_topic)
    article = f"{event_sentence} {reason_sentence} {follow_up}"

    payload = {
        "topic": clean_topic,
        "headline": headline,
        "reason": reason_sentence,
        "article": article[:520],
        "sample_titles": titles[:3],
    }
    _BRIEF_CACHE[cache_key] = (now, payload)
    return payload


def _post_ai_payload(storage: Storage, settings: dict[str, Any], question: str, market_scope: str | None = None) -> dict[str, Any]:
    summary = _summary_payload(storage, settings, market_scope)
    top_topics = summary.get("top_topics") or []
    hot_topics = summary.get("hot_topics") or []
    candidates = []
    seen = set()
    for item in top_topics + hot_topics:
        topic = (item.get("topic") or "").strip()
        if not topic:
            continue
        key = topic.lower()
        if key in seen:
            continue
        seen.add(key)
        candidates.append(item)
        if len(candidates) >= 5:
            break

    if not candidates:
        return {
            "answer": "Jag hittar inga tydliga live-trender just nu. Vänta en cykel och fråga igen om 2-3 minuter.",
            "ideas": [],
        }

    lead = candidates[0]
    lead_topic = lead.get("topic") or "ett ämne"
    lead_title = _clean_source_tail((lead.get("example_title") or "").strip()) or lead_topic
    q = (question or "").strip()
    focus = "kort video"
    q_lower = q.lower()
    if any(w in q_lower for w in ["caption", "text"]):
        focus = "caption"
    elif any(w in q_lower for w in ["hook", "öppning"]):
        focus = "hook"
    elif any(w in q_lower for w in ["script", "manus"]):
        focus = "manus"

    ideas = []
    for item in candidates[:3]:
        topic = item.get("topic") or "okänt ämne"
        title = _clean_source_tail((item.get("example_title") or "").strip()) or topic
        ideas.append(
            {
                "topic": topic,
                "angle": f"Säg vad som hänt i en mening: {title}. Avsluta med en tydlig take eller fråga.",
                "hook": f"Snabb update om {topic}: det här är vad som faktiskt hänt.",
                "cta": f"Vad tycker ni om {topic}?",
            }
        )

    answer = (
        f"Bästa att posta just nu är {focus} om \"{lead_topic}\". "
        f"Börja med fakta från rubriken \"{lead_title}\", håll det till 20-30 sekunder, "
        f"och avsluta med en tydlig fråga för kommentarer."
    )
    return {"answer": answer, "ideas": ideas}


def _render_index(bootstrap_data: dict[str, Any] | None = None) -> str:
    bootstrap_json = json.dumps(bootstrap_data or {})
    template = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>TrendBot Dashboard</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #ebe5de;
      --panel: #f7f4f0;
      --muted: #625b54;
      --text: #171616;
      --line: #ddd2c5;
      --accent: #d54e1f;
    }
    body.theme-light {
      color-scheme: dark;
      --bg: #0f172a;
      --panel: #111827;
      --muted: #94a3b8;
      --text: #e2e8f0;
      --line: #243244;
      --accent: #f59e0b;
    }
    body {
      margin: 0;
      font-family: "Avenir Next", "SF Pro Text", "SF Pro Display", "Manrope", Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
    }
    body.theme-light {
      background: radial-gradient(circle at top, #1e293b 0, #0f172a 55%);
    }
    header {
      padding: 20px 24px 12px;
    }
    .topbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
      margin-bottom: 10px;
    }
    .nav-links {
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 8px;
      justify-content: flex-end;
    }
    .nav-link {
      border: 1px solid #d9c9b7;
      background: #fff8f2;
      color: #2b2118;
      border-radius: 10px;
      padding: 8px 10px;
      font-size: 13px;
      text-decoration: none;
    }
    .nav-link.active,
    .nav-link:hover {
      border-color: rgba(245, 158, 11, 0.55);
      color: #fbbf24;
      text-decoration: none;
    }
    body.theme-light .nav-link {
      border: 1px solid rgba(148, 163, 184, 0.26);
      background: rgba(15, 23, 42, 0.9);
      color: #e2e8f0;
    }
    body.theme-light .nav-link.active,
    body.theme-light .nav-link:hover {
      border-color: #fb923c;
      color: #c2410c;
    }
    h1 {
      margin: 0;
      font-size: 28px;
      font-weight: 800;
      letter-spacing: -0.02em;
      color: #121212;
      overflow-wrap: anywhere;
    }
    h2 {
      margin: 0 0 12px;
      font-size: 18px;
      font-weight: 800;
      letter-spacing: -0.01em;
      color: #1a1511;
    }
    body.theme-light h1,
    body.theme-light h2 {
      color: #f8fafc;
    }
    p { color: var(--muted); margin: 8px 0 0; font-weight: 600; }
    .sync-status {
      margin-top: 6px;
      font-size: 12px;
      color: #8b7f72;
      font-weight: 700;
    }
    .sync-status.error {
      color: #b45309;
    }
    body.theme-light .sync-status { color: #94a3b8; }
    body.theme-light .sync-status.error { color: #f59e0b; }
    main { padding: 0 24px 32px; display: grid; gap: 18px; }
    .grid { display: grid; gap: 18px; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); }
    .grid.wide { grid-template-columns: repeat(auto-fit, minmax(380px, 1fr)); }
    .card {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 18px;
      box-shadow: none;
      backdrop-filter: none;
    }
    body.theme-light .card {
      background: rgba(15, 23, 42, 0.82);
      border: 1px solid rgba(148, 163, 184, 0.18);
      box-shadow: 0 20px 60px rgba(0,0,0,.25);
    }
    ol, ul { margin: 0; padding-left: 20px; }
    li { margin: 8px 0; }
    .pill {
      display: inline-block;
      padding: 4px 10px;
      border-radius: 999px;
      background: #f4e6d8;
      color: #d56c34;
      font-size: 12px;
      margin-left: 8px;
      font-weight: 800;
    }
    .muted { color: var(--muted); font-size: 13px; font-weight: 600; }
    .row { display: flex; justify-content: space-between; gap: 12px; }
    .topic {
      font-weight: 600;
    }
    .score { color: #d56c34; font-variant-numeric: tabular-nums; font-weight: 800; }
    .source { color: #3b82f6; font-size: 12px; font-weight: 700; }
    .badge {
      display: inline-block;
      width: 10px; height: 10px; border-radius: 999px;
      margin-right: 8px; vertical-align: middle;
    }
    .metric {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin: 10px 0;
    }
    .bar {
      flex: 1;
      height: 10px;
      background: rgba(148, 163, 184, 0.12);
      border-radius: 999px;
      overflow: hidden;
    }
    .bar > span {
      display: block;
      height: 100%;
      border-radius: 999px;
      background: linear-gradient(90deg, #f59e0b, #f97316);
    }
    .chart {
      width: 100%;
      min-height: 240px;
    }
    .chart svg {
      width: 100%;
      height: 240px;
      display: block;
    }
    .chart-line {
      fill: none;
      stroke-width: 3;
      stroke-linecap: round;
      stroke-linejoin: round;
    }
    .chart-grid { stroke: rgba(148, 163, 184, 0.18); stroke-width: 1; }
    .chart-axis-label {
      fill: #94a3b8;
      font-size: 11px;
      font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    .chart-axis-label-x {
      fill: #7f90ab;
      font-size: 10px;
      font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    .legend-grid {
      display: grid;
      gap: 6px;
      margin-top: 10px;
    }
    .legend-item {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
    }
    .legend-topic {
      display: inline-flex;
      align-items: center;
      min-width: 0;
      color: var(--text);
      font-size: 13px;
    }
    .legend-value {
      color: #fbbf24;
      font-variant-numeric: tabular-nums;
      font-size: 12px;
      white-space: nowrap;
    }
    .control-row {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 8px;
    }
    .control-select, .control-btn {
      border: 1px solid var(--line);
      background: #f7f2ec;
      color: #241a12;
      border-radius: 10px;
      padding: 8px 10px;
      font-size: 13px;
      font-weight: 700;
    }
    body.theme-light .control-select, 
    body.theme-light .control-btn {
      border: 1px solid rgba(148, 163, 184, 0.26);
      background: rgba(15, 23, 42, 0.9);
      color: #e2e8f0;
    }
    .control-select {
      flex: 1;
      min-width: 0;
    }
    .control-btn {
      cursor: pointer;
      white-space: nowrap;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
    }
    .control-btn:hover {
      border-color: rgba(245, 158, 11, 0.55);
      color: #fbbf24;
      text-decoration: none;
    }
    .secondary-btn {
      border: 1px solid rgba(96, 165, 250, 0.45);
      background: rgba(30, 58, 138, 0.28);
      color: #bfdbfe;
      border-radius: 10px;
      padding: 6px 10px;
      font-size: 12px;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      white-space: nowrap;
    }
    .secondary-btn:hover {
      border-color: rgba(125, 211, 252, 0.75);
      color: #dbeafe;
      text-decoration: none;
    }
    .media-page {
      display: none;
    }
    .media-grid {
      display: grid;
      gap: 12px;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    }
    .media-images {
      display: grid;
      gap: 12px;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    }
    .media-image-card {
      border: 1px solid rgba(148, 163, 184, 0.2);
      border-radius: 14px;
      background: rgba(15, 23, 42, 0.68);
      overflow: hidden;
      text-decoration: none;
      color: inherit;
    }
    .media-image-card:hover {
      border-color: rgba(245, 158, 11, 0.55);
      text-decoration: none;
    }
    .media-image-card img {
      width: 100%;
      aspect-ratio: 4 / 3;
      object-fit: cover;
      display: block;
      background: #0b1224;
    }
    .media-image-card .label {
      padding: 8px 10px;
      font-size: 12px;
      color: #cbd5e1;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .media-image-card .sub {
      padding: 0 10px 10px;
      font-size: 11px;
      color: #93c5fd;
    }
    .login-overlay {
      position: fixed;
      inset: 0;
      background: rgba(23, 18, 15, 0.42);
      display: none;
      align-items: center;
      justify-content: center;
      z-index: 1000;
      padding: 16px;
    }
    .login-card {
      position: relative;
      width: min(420px, 100%);
      background: #fffaf4;
      border: 1px solid #d9c9b7;
      border-radius: 16px;
      padding: 18px;
      box-shadow: 0 20px 45px rgba(71, 44, 20, 0.14);
    }
    .login-close {
      position: absolute;
      top: 10px;
      right: 10px;
      width: 32px;
      height: 32px;
      border-radius: 999px;
      border: 1px solid #d9c9b7;
      background: #fff8f2;
      color: #2b2118;
      font-size: 18px;
      line-height: 1;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      justify-content: center;
    }
    .login-close:hover {
      border-color: rgba(245, 158, 11, 0.55);
      color: #d56c34;
    }
    .login-card .muted { color: #5b5045; }
    .login-input {
      width: 100%;
      box-sizing: border-box;
      margin-top: 8px;
      border: 1px solid #d9c9b7;
      background: #fff;
      color: #1b1713;
      border-radius: 10px;
      padding: 10px;
      font-size: 14px;
    }
    .login-input::placeholder { color: #8a7b6d; }
    body.theme-light .login-overlay { background: rgba(2, 6, 23, 0.82); }
    body.theme-light .login-card {
      background: rgba(15, 23, 42, 0.96);
      border: 1px solid rgba(148, 163, 184, 0.24);
      box-shadow: 0 24px 50px rgba(0, 0, 0, 0.35);
    }
    body.theme-light .login-card .muted { color: #cbd5e1; }
    body.theme-light .login-close {
      border: 1px solid rgba(148, 163, 184, 0.26);
      background: rgba(15, 23, 42, 0.9);
      color: #e2e8f0;
    }
    body.theme-light .login-close:hover {
      border-color: #fb923c;
      color: #fbbf24;
    }
    body.theme-light .login-input {
      border: 1px solid rgba(148, 163, 184, 0.26);
      background: rgba(15, 23, 42, 0.9);
      color: #e2e8f0;
    }
    body.theme-light .login-input::placeholder { color: #94a3b8; }
    .media-card {
      border: 1px solid rgba(148, 163, 184, 0.2);
      border-radius: 14px;
      padding: 14px;
      background: rgba(15, 23, 42, 0.68);
    }
    .chip-wrap {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    .chip {
      border: 1px solid rgba(148, 163, 184, 0.25);
      border-radius: 999px;
      padding: 6px 10px;
      color: #cbd5e1;
      text-decoration: none;
      font-size: 12px;
      max-width: 100%;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .chip:hover {
      border-color: rgba(245, 158, 11, 0.55);
      color: #fbbf24;
      text-decoration: none;
    }
    .filter-row {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
      margin-top: 8px;
    }
    .filter-btn {
      border: 1px solid var(--line);
      background: #f7f2ec;
      color: #241a12;
      border-radius: 999px;
      padding: 6px 10px;
      font-size: 12px;
      font-weight: 700;
      cursor: pointer;
    }
    body.theme-light .filter-btn {
      border: 1px solid rgba(148, 163, 184, 0.26);
      background: rgba(15, 23, 42, 0.9);
      color: #e2e8f0;
    }
    .filter-btn.active {
      border-color: #d56c34;
      color: #d56c34;
    }
    .why-wrap {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-top: 6px;
    }
    .why-chip {
      font-size: 11px;
      color: #a44a1e;
      background: #fff1df;
      border: 1px solid #f0caa2;
      border-radius: 999px;
      padding: 3px 8px;
      font-weight: 700;
    }
    .topic-page {
      display: none;
    }
    .studio-box {
      border: 1px solid rgba(148, 163, 184, 0.2);
      border-radius: 12px;
      padding: 12px;
      background: rgba(15, 23, 42, 0.62);
      margin-top: 8px;
    }
    a { color: #93c5fd; text-decoration: none; }
    a:hover { text-decoration: underline; }
    code { background: rgba(148,163,184,.12); padding: 2px 6px; border-radius: 6px; }
    .site-footer {
      padding: 8px 24px 28px;
    }
    .site-footer .footer-links {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
    }
    @media (max-width: 920px) {
      header { padding: 16px 14px 8px; }
      main { padding: 0 14px 20px; }
      .site-footer { padding: 8px 14px 20px; }
      h1 { font-size: clamp(30px, 11vw, 52px); line-height: 0.95; }
      .nav-links { justify-content: flex-start; }
      .nav-link, .control-btn { padding: 8px 9px; font-size: 12px; }
    }
  </style>
</head>
<body>
  <div id="login-overlay" class="login-overlay">
    <div class="login-card">
      <button id="login-close" class="login-close" type="button" aria-label="Stäng login">✕</button>
      <h2>Logga in</h2>
      <p class="muted">Konto: <code>admin</code>, <code>start</code> eller <code>pro</code></p>
      <input id="login-username" class="login-input" type="text" placeholder="username" />
      <input id="login-password" class="login-input" type="password" placeholder="password" />
      <div class="control-row" style="margin-top:10px;">
        <button id="login-submit" class="control-btn" type="button">Logga in</button>
        <span id="login-status" class="muted"></span>
      </div>
    </div>
  </div>
  <header>
    <div class="topbar">
      <h1>TrendBot Dashboard</h1>
      <nav class="nav-links">
        <span id="role-badge" class="pill" style="margin-right:6px;">Plan: Start</span>
        <a id="nav-home" class="nav-link" href="https://trendbot.se" rel="noreferrer">Hem</a>
        <a id="nav-dashboard" class="nav-link" href="?">Dashboard</a>
        <a id="nav-topic" class="nav-link" href="?view=topic">Topic</a>
        <a id="nav-media" class="nav-link" data-min-role="pro" href="?view=media">Bilder</a>
        <button id="refresh-btn" class="control-btn" type="button">Uppdatera</button>
        <button id="theme-toggle" class="control-btn" type="button" aria-label="toggle theme">Light mode</button>
        <button id="logout-btn" class="control-btn" type="button">Logga ut</button>
      </nav>
    </div>
    <p>Live overview of the strongest topics and the latest observations.</p>
    <div id="sync-status" class="sync-status">Synkar...</div>
  </header>
  <main id="dashboard-page">
    <section class="card" data-min-role="start">
      <h2>Filters <span class="pill">live view</span></h2>
      <div class="filter-row">
        <button id="scope-sweden" class="filter-btn active" type="button">Sweden</button>
        <button id="scope-global" class="filter-btn" data-min-role="start" type="button">Global / America</button>
      </div>
      <div class="filter-row">
        <button class="filter-btn active" data-filter="all" type="button">Allt</button>
        <button class="filter-btn" data-filter="svenskt" type="button">Svenskt</button>
        <button class="filter-btn" data-filter="drama" type="button">Drama</button>
        <button class="filter-btn" data-filter="tv" type="button">TV</button>
        <button class="filter-btn" data-filter="musik" type="button">Musik</button>
      </div>
      <div class="filter-row">
        <button class="filter-btn" data-window="2" type="button">Senaste 2h</button>
        <button class="filter-btn active" data-window="24" type="button">Senaste 24h</button>
      </div>
    </section>
    <div class="grid wide">
      <section class="card">
        <h2>Daily Top 10 <span class="pill">stable • last 24h</span></h2>
        <div class="control-row">
          <select id="top10-select" class="control-select">
            <option>Loading...</option>
          </select>
          <button id="top10-more" class="control-btn" type="button">Show more ▾</button>
        </div>
        <div id="top10-focus" class="muted" style="margin-bottom:8px;">Loading...</div>
        <ol id="top10"><li class="muted">Loading...</li></ol>
        <p class="muted">Only topics with at least 3 mentions can enter.</p>
      </section>
      <section class="card">
        <h2>Hot Mentions <span class="pill">fast • last 60m</span></h2>
        <ol id="hot-topics"><li class="muted">Loading...</li></ol>
      </section>
      <section class="card" data-min-role="lite">
        <h2>Topic Rank <span class="pill">färgade kategorier</span></h2>
        <div id="categories"><div class="muted">Loading...</div></div>
      </section>
      <section class="card" data-min-role="lite">
        <h2>Topic Clusters <span class="pill">clustered stories</span></h2>
        <ul id="clusters"><li class="muted">Loading...</li></ul>
      </section>
      <section class="card" data-min-role="pro">
        <h2>Vad Folk Tycker <span class="pill">känsla per ämne</span></h2>
        <ul id="reactions"><li class="muted">Loading...</li></ul>
      </section>
      <section class="card" data-min-role="start">
        <h2>Watchlist <span class="pill">people/program</span></h2>
        <p class="muted">Spara ämnen du vill bevaka extra noga.</p>
        <div id="watchlist-items"><div class="muted">Ingen watchlist ännu.</div></div>
      </section>
    </div>
    <div class="grid wide">
      <section class="card" data-min-role="start">
        <h2>Post AI <span class="pill">what to post now</span></h2>
        <div class="control-row">
          <input id="post-ai-question" class="control-select" type="text" placeholder="Fråga: vad ska jag posta just nu?" />
          <button id="post-ai-ask" class="control-btn" type="button">Fråga AI</button>
        </div>
        <div id="post-ai-answer" class="muted">Skriv en fråga och klicka på Fråga AI.</div>
      </section>
    </div>
    <div class="grid wide">
      <section class="card" data-min-role="pro">
        <h2>Trend Graphs</h2>
        <div class="chart" id="featured-chart"></div>
        <p class="muted" id="featured-label">Loading...</p>
      </section>
      <section class="card" data-min-role="admin">
        <h2>Backtest Snapshot</h2>
        <div id="backtest"><div class="muted">Loading...</div></div>
      </section>
    </div>
    <div class="grid wide">
      <section class="card" data-min-role="pro">
        <h2>Recent Observations</h2>
        <p class="muted" id="recent-status">Loading...</p>
        <ul id="recent"><li class="muted">Loading...</li></ul>
      </section>
      <section class="card" data-min-role="pro">
        <h2>Daily Series</h2>
        <div class="chart" id="cluster-chart"></div>
        <p class="muted" id="cluster-label">Loading...</p>
      </section>
    </div>
    <section class="card" data-min-role="pro">
      <h2>Tips</h2>
      <p class="muted">Open the Discord alerts for sharper context, or use the JSON endpoints at <code>/api/summary</code> and <code>/api/recent</code>.</p>
    </section>
    <section class="card" data-min-role="pro">
      <h2>What The Numbers Mean</h2>
      <div class="metric">
        <div><strong>Trend score</strong><div class="muted">A 0-100 score. Higher means hotter. It mixes mentions, baseline, source agreement, and cluster strength.</div></div>
        <div class="score">heat</div>
      </div>
      <div class="metric">
        <div><strong>Mentions</strong><div class="muted">Shown as new/fetched. New = unseen matches this cycle. Fetched = total fetched before de-duplication.</div></div>
        <div class="score">count</div>
      </div>
      <div class="metric">
        <div><strong>Samples</strong><div class="muted">How many observation points were used to build the total.</div></div>
        <div class="score">history</div>
      </div>
      <div class="metric">
        <div><strong>Sources</strong><div class="muted">How many sources agreed on the same topic or cluster.</div></div>
        <div class="score">agreement</div>
      </div>
      <div class="metric">
        <div><strong>Chart</strong><div class="muted">Time on the x-axis, mentions on the y-axis.</div></div>
        <div class="score">trend</div>
      </div>
    </section>
  </main>
  <main id="topic-page" class="topic-page">
    <section class="card">
      <div class="row" style="align-items:center;">
        <h2 style="margin:0;">Topic Detail</h2>
        <a class="control-btn" href="?">Tillbaka till dashboard</a>
      </div>
      <p class="muted" id="topic-subtitle">Välj en trend från listan.</p>
      <div id="topic-title" class="topic" style="font-size:22px; margin-top:8px;">No topic selected</div>
      <div class="why-wrap" id="topic-why"></div>
      <div class="filter-row">
        <button id="watchlist-toggle" class="filter-btn" data-min-role="start" type="button">Lägg till i watchlist</button>
      </div>
    </section>
    <div class="grid wide">
      <section class="card">
        <h2>Tidslinje</h2>
        <div class="chart" id="topic-chart"></div>
      </section>
      <section class="card">
        <h2>Källor</h2>
        <ul id="topic-sources"><li class="muted">No topic selected</li></ul>
      </section>
    </div>
    <div class="grid wide">
      <section class="card">
        <h2>Känsla</h2>
        <div id="topic-sentiment" class="muted">No topic selected</div>
      </section>
      <section class="card">
        <h2>Post Studio</h2>
        <div id="post-studio" class="muted">No topic selected</div>
      </section>
    </div>
    <section class="card">
      <h2>Media</h2>
      <div id="topic-media-links" class="chip-wrap"></div>
    </section>
  </main>
  <main id="media-page" class="media-page">
    <section class="card">
      <div class="row" style="align-items:center;">
        <h2 style="margin:0;">Bilder & Video-bibliotek</h2>
        <a class="control-btn" href="?">Tillbaka till dashboard</a>
      </div>
      <p class="muted">Relaterade media-länkar för trenden just nu.</p>
      <div id="media-selected-topic" class="topic" style="margin-top:10px; font-size:18px;">Loading...</div>
    </section>
    <section class="card">
      <h2>Media Sources</h2>
      <div id="media-links" class="media-grid"></div>
    </section>
    <section class="card">
      <h2>Bildbibliotek</h2>
      <p class="muted">Relaterade bilder för trendämnet (Google News).</p>
      <div id="media-image-grid" class="media-images"></div>
    </section>
    <section class="card">
      <h2>Videobibliotek</h2>
      <p class="muted">Relaterade videor för trendämnet (Google News video-sök).</p>
      <div id="media-video-grid" class="media-images"></div>
    </section>
    <section class="card">
      <h2>Byt Trendämne</h2>
      <p class="muted">Välj ett annat ämne från dagens topptrender.</p>
      <div id="media-topic-chips" class="chip-wrap"></div>
    </section>
  </main>
  <footer class="site-footer">
    <div class="footer-links">
      <a class="nav-link" href="/privacy" target="_blank" rel="noreferrer">Integritet</a>
      <a class="nav-link" href="/cookies" target="_blank" rel="noreferrer">Cookies</a>
      <a class="nav-link" href="/legal/dsr" target="_blank" rel="noreferrer">Dina rättigheter</a>
    </div>
  </footer>
  <div id="cookie-consent-banner" style="display:none; position:fixed; left:16px; right:16px; bottom:16px; z-index:2000; background:#fffaf4; border:1px solid #d9c9b7; border-radius:14px; padding:12px 14px; box-shadow:0 10px 24px rgba(0,0,0,.12);">
    <div style="display:flex; gap:10px; align-items:center; flex-wrap:wrap;">
      <div style="flex:1; min-width:260px; color:#2c2219; font-size:14px;">
        Vi använder nödvändiga cookies för inloggning och säkerhet. Icke-nödvändig spårning används endast efter samtycke.
        Läs mer i <a href="/cookies" target="_blank" rel="noreferrer">Cookiepolicy</a>.
      </div>
      <button id="cookie-reject-btn" class="control-btn" type="button">Avvisa</button>
      <button id="cookie-accept-btn" class="control-btn" type="button" style="border-color:#d56c34;color:#d56c34;">Acceptera</button>
    </div>
  </div>
  <script>
    const BOOTSTRAP_DATA = __BOOTSTRAP_DATA__;
    const OPTIONAL_TRACKING_ENABLED = Boolean(BOOTSTRAP_DATA.optional_tracking_enabled);
    const COOKIE_CONSENT_KEY = 'trendbot_cookie_consent_v1';
    const categoryColors = {
      pop_culture: '#f59e0b',
      music: '#ec4899',
      politics: '#3b82f6',
      news: '#06b6d4',
      internet: '#22c55e',
      gaming: '#8b5cf6',
      default: '#f97316',
    };
    function colorFor(category) {
      return categoryColors[category] || categoryColors.default;
    }
    function escapeHtml(value) {
      return String(value)
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
    }
    function mediaPageLink(topic) {
      const params = new URLSearchParams();
      params.set('view', 'media');
      params.set('topic', topic || '');
      return `?${params.toString()}`;
    }
    function mediaSources(topic) {
      const encoded = encodeURIComponent(topic || '');
      return [
        {
          label: 'Google Images',
          description: 'Snabb bildsökning på ämnet.',
          url: `https://www.google.com/search?tbm=isch&q=${encoded}`,
        },
        {
          label: 'Google Videos',
          description: 'Videoresultat från flera källor.',
          url: `https://www.google.com/search?tbm=vid&q=${encoded}`,
        },
        {
          label: 'YouTube',
          description: 'Relaterade videor och klipp.',
          url: `https://www.youtube.com/results?search_query=${encoded}`,
        },
        {
          label: 'TikTok',
          description: 'Korta klipp och trendinnehåll.',
          url: `https://www.tiktok.com/search?q=${encoded}`,
        },
        {
          label: 'Giphy',
          description: 'GIFs och reaktionsmedia.',
          url: `https://giphy.com/search/${encoded}`,
        },
        {
          label: 'Google News',
          description: 'Nyheter och kontext med käll-länkar.',
          url: `https://news.google.com/search?q=${encoded}`,
        },
      ];
    }
    function chartGuides(width, height, pad, minValue, maxValue, tickCount = 4) {
      const ticks = [];
      const span = Math.max(maxValue - minValue, 1);
      const steps = Math.max(tickCount - 1, 1);
      for (let i = 0; i < tickCount; i += 1) {
        const ratio = i / steps;
        const value = maxValue - (span * ratio);
        const y = pad + (height - pad * 2) * ratio;
        ticks.push({ y, value: Math.max(0, value) });
      }
      const lines = ticks.map((tick) =>
        `<line class="chart-grid" x1="${pad}" y1="${tick.y}" x2="${width - pad}" y2="${tick.y}" />`
      ).join('');
      const labels = ticks.map((tick) =>
        `<text class="chart-axis-label" x="${pad - 6}" y="${tick.y + 4}" text-anchor="end">${Math.round(tick.value)}</text>`
      ).join('');
      return { lines, labels };
    }
    function shortTimeLabelFromPoint(point) {
      const ts = point && point.bucket_ts ? Number(point.bucket_ts) : 0;
      if (!ts) return '';
      const d = new Date(ts * 1000);
      return d.toLocaleTimeString('sv-SE', {
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
        timeZone: 'Europe/Stockholm',
      });
    }
    function xAxisLabels(points, width, height, pad, tickCount = 5) {
      if (!points || points.length === 0) {
        return '';
      }
      const baselineY = height - pad;
      const labelY = height - 6;
      const maxTicks = Math.max(2, tickCount);
      const steps = Math.max(1, maxTicks - 1);
      const labels = [];
      for (let i = 0; i < maxTicks; i += 1) {
        const ratio = i / steps;
        const index = Math.min(points.length - 1, Math.round((points.length - 1) * ratio));
        const x = pad + ((width - pad * 2) * (index / Math.max(1, points.length - 1)));
        labels.push(
          `<line class="chart-grid" x1="${x}" y1="${baselineY}" x2="${x}" y2="${baselineY + 4}" />` +
          `<text class="chart-axis-label-x" x="${x}" y="${labelY}" text-anchor="middle">${shortTimeLabelFromPoint(points[index])}</text>`
        );
      }
      return labels.join('');
    }
    function lineChart(points, color) {
      if (!points || !points.length) {
        return '<div class="muted">No history yet.</div>';
      }
      const width = 700;
      const height = 240;
      const pad = 32;
      const values = points.map((item) => item.total_mentions || 0);
      const maxValue = Math.max(...values, 1);
      const minValue = Math.min(...values, 0);
      const span = Math.max(maxValue - minValue, 1);
      const step = points.length === 1 ? 0 : (width - pad * 2) / (points.length - 1);
      const coords = points.map((item, idx) => {
        const x = pad + (step * idx);
        const y = height - pad - (((item.total_mentions || 0) - minValue) / span) * (height - pad * 2);
        return { x, y, value: item.total_mentions || 0, label: item.label || '' };
      });
      const path = coords.map((point, index) => `${index === 0 ? 'M' : 'L'} ${point.x} ${point.y}`).join(' ');
      const last = coords[coords.length - 1];
      const guides = chartGuides(width, height, pad, minValue, maxValue, 4);
      const xLabels = xAxisLabels(points, width, height, pad, 5);
      return `
        <svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-label="trend chart">
          ${guides.lines}
          ${guides.labels}
          ${xLabels}
          <defs>
            <linearGradient id="trendFill" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stop-color="${color}" stop-opacity="0.35" />
              <stop offset="100%" stop-color="${color}" stop-opacity="0.02" />
            </linearGradient>
          </defs>
          <path d="${path}" class="chart-line" stroke="${color}" />
          <path d="${path} L ${last.x} ${height - pad} L ${pad} ${height - pad} Z" fill="url(#trendFill)"></path>
          ${coords.map((point) => `<circle cx="${point.x}" cy="${point.y}" r="3.5" fill="${color}" />`).join('')}
        </svg>
      `;
    }
    function multiLineChart(seriesList) {
      if (!seriesList || !seriesList.length) {
        return '<div class="muted">No history yet.</div>';
      }
      const width = 700;
      const height = 240;
      const pad = 32;
      const maxPoints = Math.max(...seriesList.map((item) => (item.series || []).length), 0);
      if (maxPoints === 0) {
        return '<div class="muted">No history yet.</div>';
      }

      const allValues = [];
      for (const item of seriesList) {
        for (const point of (item.series || [])) {
          allValues.push(point.total_mentions || 0);
        }
      }
      const maxValue = Math.max(...allValues, 1);
      const minValue = Math.min(...allValues, 0);
      const span = Math.max(maxValue - minValue, 1);
      const step = maxPoints === 1 ? 0 : (width - pad * 2) / (maxPoints - 1);
      const guides = chartGuides(width, height, pad, minValue, maxValue, 5);
      const longestSeries = [...seriesList].sort((a, b) => (b.series || []).length - (a.series || []).length)[0];
      const xLabels = xAxisLabels(longestSeries ? (longestSeries.series || []) : [], width, height, pad, 6);

      const svgLines = seriesList.map((item) => {
        const color = colorFor(item.category);
        const coords = (item.series || []).map((point, idx) => {
          const x = pad + (step * idx);
          const y = height - pad - (((point.total_mentions || 0) - minValue) / span) * (height - pad * 2);
          return { x, y };
        });
        if (!coords.length) {
          return '';
        }
        const path = coords.map((point, index) => `${index === 0 ? 'M' : 'L'} ${point.x} ${point.y}`).join(' ');
        const last = coords[coords.length - 1];
        return `
          <path d="${path}" class="chart-line" stroke="${color}" />
          <circle cx="${last.x}" cy="${last.y}" r="4" fill="${color}" />
        `;
      }).join('');

      const legend = [...seriesList]
        .sort((a, b) => {
          const aLast = (a.series && a.series.length) ? (a.series[a.series.length - 1].total_mentions || 0) : 0;
          const bLast = (b.series && b.series.length) ? (b.series[b.series.length - 1].total_mentions || 0) : 0;
          return bLast - aLast;
        })
        .map((item) => {
          const lastValue = (item.series && item.series.length) ? (item.series[item.series.length - 1].total_mentions || 0) : 0;
          return `
            <div class="legend-item">
              <div class="legend-topic">
                <span class="badge" style="background:${colorFor(item.category)}"></span>
                ${escapeHtml(item.cluster_label)}
              </div>
              <div class="legend-value">${lastValue} now</div>
            </div>
          `;
        }).join('');

      return `
        <svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-label="top 5 daily series">
          ${guides.lines}
          ${guides.labels}
          ${xLabels}
          ${svgLines}
        </svg>
        <div class="legend-grid">${legend}</div>
      `;
    }
    let top10ShowAll = false;
    let top10SelectedKey = '';
    let lastSummary = null;
    let lastRecent = null;
    let marketScope = 'sweden';
    let userRole = 'lite';
    const ROLE_RANK = { lite: 0, start: 1, pro: 2, admin: 3 };
    let activeFilter = 'all';
    let activeWindowHours = 24;
    let currentTopicKey = '';
    let loadInFlight = false;
    const WATCHLIST_KEY = 'trendbot_watchlist_v1';
    const THEME_KEY = 'trendbot_theme_v1';
    function nowUtcSeconds() {
      return Math.floor(Date.now() / 1000);
    }
    function topicText(item) {
      return `${item.topic || ''} ${item.example_title || ''} ${item.category || ''}`.toLowerCase();
    }
    function setSyncStatus(message, isError = false) {
      const el = document.getElementById('sync-status');
      if (!el) return;
      el.textContent = message;
      el.classList.toggle('error', Boolean(isError));
    }
    function matchesFilter(item) {
      if (!item) return false;
      const text = topicText(item);
      if (activeFilter === 'svenskt') {
        return ['svensk', 'sverige', 'melodifestivalen', 'tv4', 'svt', 'nöje'].some((x) => text.includes(x));
      }
      if (activeFilter === 'drama') {
        return ['drama', 'skandal', 'bråk', 'chock', 'rasar', 'kritik', 'backlash', 'controversy'].some((x) => text.includes(x));
      }
      if (activeFilter === 'tv') {
        return ['tv', 'serie', 'program', 'svt', 'tv4', 'idol', 'lets dance', 'masked singer'].some((x) => text.includes(x));
      }
      if (activeFilter === 'musik') {
        return ['musik', 'music', 'song', 'album', 'k-pop', 'eurovision', 'melodifestivalen'].some((x) => text.includes(x));
      }
      return true;
    }
    function withinWindow(item) {
      if (!item || !item.latest_observed_at) return true;
      return item.latest_observed_at >= (nowUtcSeconds() - (activeWindowHours * 3600));
    }
    function filtered(items) {
      return (items || []).filter((item) => matchesFilter(item) && withinWindow(item));
    }
    function applyScopeButtons() {
      const se = document.getElementById('scope-sweden');
      const gl = document.getElementById('scope-global');
      if (!se || !gl) return;
      se.classList.toggle('active', marketScope === 'sweden');
      gl.classList.toggle('active', marketScope === 'global');
    }
    function applyTheme(theme) {
      const isDark = theme === 'dark';
      document.body.classList.toggle('theme-light', isDark);
      const btn = document.getElementById('theme-toggle');
      if (btn) btn.textContent = isDark ? 'Orange mode' : 'Dark mode';
    }
    function initTheme() {
      let theme = 'warm';
      try {
        const saved = localStorage.getItem(THEME_KEY);
        if (saved === 'warm' || saved === 'dark') theme = saved;
        if (saved === 'light') theme = 'warm';
      } catch {}
      applyTheme(theme);
    }
    function toggleTheme() {
      const next = document.body.classList.contains('theme-light') ? 'warm' : 'dark';
      applyTheme(next);
      try { localStorage.setItem(THEME_KEY, next); } catch {}
    }
    function initCookieConsent() {
      const banner = document.getElementById('cookie-consent-banner');
      const acceptBtn = document.getElementById('cookie-accept-btn');
      const rejectBtn = document.getElementById('cookie-reject-btn');
      if (!banner || !acceptBtn || !rejectBtn) return;
      if (!OPTIONAL_TRACKING_ENABLED) return;
      let current = '';
      try { current = localStorage.getItem(COOKIE_CONSENT_KEY) || ''; } catch {}
      if (current === 'accepted' || current === 'rejected') return;
      banner.style.display = 'block';
      acceptBtn.addEventListener('click', () => {
        try { localStorage.setItem(COOKIE_CONSENT_KEY, 'accepted'); } catch {}
        banner.style.display = 'none';
      });
      rejectBtn.addEventListener('click', () => {
        try { localStorage.setItem(COOKIE_CONSENT_KEY, 'rejected'); } catch {}
        banner.style.display = 'none';
      });
    }
    function applyRoleUI() {
      const roleBadge = document.getElementById('role-badge');
      if (roleBadge) {
        const labelByRole = {
          lite: 'Plan: Free',
          start: 'Plan: Start',
          pro: 'Plan: Pro',
          admin: 'Plan: Admin',
        };
        roleBadge.textContent = labelByRole[userRole] || `Plan: ${userRole}`;
      }
      const logoutBtn = document.getElementById('logout-btn');
      if (logoutBtn) logoutBtn.textContent = userRole === 'lite' ? 'Logga in' : 'Logga ut';
      document.querySelectorAll('[data-min-role]').forEach((el) => {
        const required = (el.getAttribute('data-min-role') || 'start').toLowerCase();
        const canSee = (ROLE_RANK[userRole] || 0) >= (ROLE_RANK[required] || 0);
        el.style.display = canSee ? '' : 'none';
      });
      if ((userRole === 'start' || userRole === 'lite') && marketScope === 'global') {
        marketScope = 'sweden';
        applyScopeButtons();
      }
    }
    function whyTrendingChips(item) {
      const chips = [];
      chips.push(`${item.total_mentions || 0} mentions`);
      chips.push(`${item.source_count || 0} källor med träff`);
      if ((item.trend_score || 0) >= 85) chips.push('high heat');
      if ((item.latest_observed_at || 0) >= (nowUtcSeconds() - 7200)) chips.push('very fresh');
      const t = topicText(item);
      if (['drama', 'skandal', 'bråk', 'chock', 'backlash', 'controversy'].some((x) => t.includes(x))) chips.push('strong reactions');
      return chips.slice(0, 4);
    }
    function chipsHtml(item) {
      return `<div class="why-wrap">${whyTrendingChips(item).map((chip) => `<span class="why-chip">${escapeHtml(chip)}</span>`).join('')}</div>`;
    }
    function topicLink(item) {
      return `?view=topic&key=${encodeURIComponent(item.cluster_key || '')}`;
    }
    function canOpenTopic() {
      return (ROLE_RANK[userRole] || 0) >= (ROLE_RANK.start || 1);
    }
    function getWatchlist() {
      try {
        const raw = localStorage.getItem(WATCHLIST_KEY);
        const data = raw ? JSON.parse(raw) : [];
        return Array.isArray(data) ? data : [];
      } catch {
        return [];
      }
    }
    function setWatchlist(items) {
      try {
        localStorage.setItem(WATCHLIST_KEY, JSON.stringify(items.slice(0, 25)));
      } catch {}
    }
    function watchlistHas(key) {
      return getWatchlist().some((x) => x.key === key);
    }
    function renderWatchlist() {
      const wrap = document.getElementById('watchlist-items');
      const items = getWatchlist();
      if (!items.length) {
        wrap.innerHTML = '<div class="muted">Ingen watchlist ännu.</div>';
        return;
      }
      wrap.innerHTML = `<div class="chip-wrap">${items.map((item) => `<a class="chip" href="?view=topic&key=${encodeURIComponent(item.key)}">${escapeHtml(item.topic)}</a>`).join('')}</div>`;
    }
    function toggleWatchlistCurrent() {
      if (!lastSummary || !currentTopicKey) return;
      const all = [...(lastSummary.top_topics || []), ...(lastSummary.hot_topics || [])];
      const current = all.find((x) => x.cluster_key === currentTopicKey);
      if (!current) return;
      const list = getWatchlist();
      const idx = list.findIndex((x) => x.key === currentTopicKey);
      if (idx >= 0) {
        list.splice(idx, 1);
      } else {
        list.unshift({ key: currentTopicKey, topic: current.topic, category: current.category || 'default' });
      }
      setWatchlist(list);
      renderWatchlist();
      updateWatchlistButton();
    }
    function updateWatchlistButton() {
      const btn = document.getElementById('watchlist-toggle');
      if (!btn) return;
      btn.textContent = watchlistHas(currentTopicKey) ? 'Ta bort från watchlist' : 'Lägg till i watchlist';
    }
    function renderTop10(summary) {
      const selectEl = document.getElementById('top10-select');
      const moreBtn = document.getElementById('top10-more');
      const focusEl = document.getElementById('top10-focus');
      const listEl = document.getElementById('top10');
      const allItems = filtered(summary.top_topics || []);

      if (!allItems.length) {
        selectEl.innerHTML = '<option>No topics yet</option>';
        selectEl.disabled = true;
        moreBtn.style.display = 'none';
        focusEl.textContent = 'No stable topics yet.';
        listEl.innerHTML = '<li class="muted">No data yet.</li>';
        return;
      }

      const visibleItems = top10ShowAll ? allItems : allItems.slice(0, 5);
      if (!top10SelectedKey || !visibleItems.some((item) => item.cluster_key === top10SelectedKey)) {
        top10SelectedKey = visibleItems[0].cluster_key;
      }

      selectEl.disabled = false;
      selectEl.innerHTML = visibleItems.map((item, idx) => `
        <option value="${item.cluster_key}">${idx + 1}. ${escapeHtml(item.topic)}</option>
      `).join('');
      selectEl.value = top10SelectedKey;

      moreBtn.style.display = allItems.length > 5 ? 'inline-block' : 'none';
      moreBtn.textContent = top10ShowAll ? 'Show less ▴' : 'Show more ▾';

      const selected = allItems.find((item) => item.cluster_key === top10SelectedKey) || visibleItems[0];
      let freshnessNote = '';
      if ((summary.data_mode || '').startsWith('fallback_')) {
        freshnessNote = ` • showing latest known snapshot (${escapeHtml(summary.latest_known_observed_at_human || 'older data')})`;
      }
      focusEl.innerHTML = `
        <strong>${escapeHtml(selected.topic)}</strong>
        <span class="source">${selected.category}</span>
        • ${selected.total_mentions} mentions • score ${selected.trend_score.toFixed(1)} / 100${freshnessNote}
      `;

      listEl.innerHTML = visibleItems.map((item) => `
        <li>
          <div class="row">
            <div>
              <span class="badge" style="background:${colorFor(item.category)}"></span>
              <span class="topic">${item.topic}</span>
              <span class="source">${item.category}</span>
            </div>
            <div class="row" style="align-items:center;">
              ${canOpenTopic() ? `<a class="secondary-btn" href="${topicLink(item)}">Open topic</a>` : ``}
              <div class="score">${item.trend_score.toFixed(1)}</div>
            </div>
          </div>
          <div class="muted">${item.total_mentions} mentions across ${item.samples} samples • ${item.source_count} källor med träff • seen ${item.latest_observed_at_human} • published ${item.latest_published_at_human || '-'}</div>
          ${chipsHtml(item)}
          <div class="muted">Cluster: ${escapeHtml(item.cluster_label || item.topic)}</div>
          <div class="muted">Trend score: ${item.trend_score.toFixed(1)} / 100</div>
          ${item.example_title ? `<div class="muted">About: ${escapeHtml(item.example_title)}</div>` : ''}
          <div class="muted"><a href="${item.link}" target="_blank" rel="noreferrer">Open topic link</a></div>
        </li>
      `).join('');
    }
    document.getElementById('top10-select').addEventListener('change', (event) => {
      top10SelectedKey = event.target.value;
      if (lastSummary) {
        renderTop10(lastSummary);
      }
    });
    document.getElementById('top10-more').addEventListener('click', () => {
      top10ShowAll = !top10ShowAll;
      if (lastSummary) {
        renderTop10(lastSummary);
      }
    });
    document.getElementById('watchlist-toggle').addEventListener('click', () => {
      toggleWatchlistCurrent();
    });
    document.getElementById('scope-sweden').addEventListener('click', async () => {
      marketScope = 'sweden';
      applyScopeButtons();
      await loadData();
    });
    document.getElementById('scope-global').addEventListener('click', async () => {
      if ((ROLE_RANK[userRole] || 0) < (ROLE_RANK.start || 1)) {
        marketScope = 'sweden';
        applyScopeButtons();
        return;
      }
      marketScope = 'global';
      applyScopeButtons();
      await loadData();
    });
    for (const btn of document.querySelectorAll('[data-filter]')) {
      btn.addEventListener('click', () => {
        activeFilter = btn.getAttribute('data-filter') || 'all';
        for (const other of document.querySelectorAll('[data-filter]')) other.classList.remove('active');
        btn.classList.add('active');
        if (lastSummary) loadData();
      });
    }
    for (const btn of document.querySelectorAll('[data-window]')) {
      btn.addEventListener('click', () => {
        activeWindowHours = Number(btn.getAttribute('data-window') || '24');
        for (const other of document.querySelectorAll('[data-window]')) other.classList.remove('active');
        btn.classList.add('active');
        if (lastSummary) loadData();
      });
    }
    function bestPublishTime(item) {
      const cat = (item.category || '').toLowerCase();
      if (cat.includes('music')) return '19:30 CEST';
      if (cat.includes('internet')) return '20:30 CEST';
      if (cat.includes('pop')) return '19:00 CEST';
      return '18:30 CEST';
    }
    function postStudioHtml(item) {
      const topic = item.topic || 'Det här';
      const ex = item.example_title || '';
      const cat = (item.category || '').toLowerCase();
      const sourceTail = /\\s[-–—]\\s(?:Aftonbladet|Expressen|SVT(?: Nyheter)?|TV4(?: Nyheterna)?|Omni|Reuters|AP News|BBC|People\\.com|Billboard|Variety|The Verge|Yahoo|Fox \\d+|[A-Za-z0-9.-]+\\.(?:se|com|org|net))$/i;
      const cleanedExample = ex.replace(sourceTail, '').trim();
      const hookOptions = [
        `POV: du missade helt vad som hände kring ${topic}`,
        `${topic}: min ärliga take på 30 sek`,
        `Okej, vi måste prata om ${topic}`,
        `Snabb förklaring: vad som faktiskt hänt kring ${topic}`,
      ];
      if (cat.includes('music')) hookOptions.unshift(`${topic} - varför alla snackar om detta i musik just nu`);
      if (cat.includes('tv')) hookOptions.unshift(`${topic} - det här betyder det för programmet/serien`);
      const hook = hookOptions[Math.abs(topic.length + ex.length) % hookOptions.length];
      const caption = cleanedExample
        ? `${cleanedExample}. Vad tänker ni om det här?`
        : `Det här har fått mycket uppmärksamhet idag. Vad tänker ni?`;
      const cta = 'Vilken take har du? Skriv i kommentarerna.';
      const timing = bestPublishTime(item);
      const fallbackArticle = cleanedExample
        ? `${cleanedExample}. I praktiken betyder det att läget i ${topic.toLowerCase()} redan har ändrats och att nästa beslut nu ligger hos de personer som nämns i nyheten. Om du vill fatta det snabbt: håll koll på nästa officiella besked och om bytet eller konflikten bekräftas i fler oberoende rapporter under dagen.`
        : `${topic} har fått nya uppgifter som redan påverkar hur läget ser ut just nu. Det viktigaste för snabb överblick är att se vad som är bekräftat, vem som faktiskt uttalat sig och om nästa uppdatering ändrar bilden ytterligare.`;
      return `
        <div class="studio-box"><strong>Hook</strong><div class="muted">${escapeHtml(hook)}</div></div>
        <div class="studio-box"><strong>Caption</strong><div class="muted">${escapeHtml(caption)}</div></div>
        <div class="studio-box"><strong>CTA</strong><div class="muted">${escapeHtml(cta)}</div></div>
        <div class="studio-box"><strong>Bästa posttid</strong><div class="muted">${timing}</div></div>
        <div class="studio-box"><strong>Exempelartikel (~60 ord)</strong><div id="post-article-text" class="muted">${escapeHtml(fallbackArticle)}</div></div>
      `;
    }

    async function fetchApiJson(path) {
      const candidates = [path];
      if (window.location.protocol === 'file:' || window.location.hostname === 'localhost') {
        candidates.push(`http://127.0.0.1:8000${path}`);
      }
      let lastErr = null;
      for (const url of candidates) {
        try {
          const res = await fetch(url, { credentials: 'include' });
          if (!res.ok) throw new Error(`${res.status} ${res.statusText}`.trim());
          return await res.json();
        } catch (err) {
          lastErr = err;
        }
      }
      throw lastErr || new Error('Load failed');
    }

    async function loadTopicBrief(item) {
      const target = document.getElementById('post-article-text');
      if (!target || !item || !item.topic) return;
      const topicKey = (item.cluster_key || item.topic || '').toString();
      target.setAttribute('data-topic-key', topicKey);
      try {
        const payload = await fetchApiJson(`/api/brief?topic=${encodeURIComponent(item.topic)}`);
        if (target.getAttribute('data-topic-key') !== topicKey) return;
        const text = (payload && payload.article) ? payload.article : '';
        if (text) target.textContent = text;
      } catch (_err) {
        // Keep fallback article text if brief fetch fails.
      }
    }
    function renderTopicPage(summary) {
      const params = new URLSearchParams(window.location.search || '');
      const key = (params.get('key') || currentTopicKey || '').trim();
      const all = filtered([...(summary.top_topics || []), ...(summary.hot_topics || [])]);
      const uniq = all.filter((item, idx, arr) => arr.findIndex((x) => x.cluster_key === item.cluster_key) === idx);
      const selected = uniq.find((x) => x.cluster_key === key) || uniq[0];
      if (!selected) {
        document.getElementById('topic-title').textContent = 'No topic selected';
        return;
      }
      currentTopicKey = selected.cluster_key;
      document.getElementById('topic-title').textContent = selected.topic;
      document.getElementById('topic-subtitle').textContent = selected.example_title || 'Topic detail';
      document.getElementById('topic-why').innerHTML = whyTrendingChips(selected).map((chip) => `<span class="why-chip">${escapeHtml(chip)}</span>`).join('');

      const series = (summary.cluster_multi_series_all || []).find((x) => x.cluster_key === selected.cluster_key);
      document.getElementById('topic-chart').innerHTML = lineChart(series ? (series.series || []) : [], colorFor(selected.category));

      const recentItems = (lastRecent && lastRecent.items) ? lastRecent.items : [];
      const sourceRows = recentItems
        .filter((r) => topicText({ topic: selected.topic, example_title: selected.example_title }).includes((r.topic || '').toLowerCase()) || (r.topic || '').toLowerCase().includes(selected.topic.toLowerCase().split(' ')[0]))
        .slice(0, 8);
      document.getElementById('topic-sources').innerHTML = sourceRows.length
        ? sourceRows.map((r) => `<li><span class="source">${escapeHtml(r.source)}</span> • <span class="muted">${escapeHtml(r.observed_at_human)}</span></li>`).join('')
        : `<li class="muted">${selected.source_count} källor i signalen just nu.</li>`;

      const reaction = (summary.reaction_topics || []).find((r) => (r.display_topic || r.topic) === selected.topic);
      document.getElementById('topic-sentiment').innerHTML = reaction
        ? `<div class="metric"><div><strong>${escapeHtml(reaction.mood)}</strong><div class="muted">Känsloscore ${reaction.sentiment_score} • Reaktionsstyrka ${reaction.intensity}/100</div></div><div class="score">${reaction.intensity}</div></div>`
        : '<div class="muted">Ingen känslodata ännu.</div>';

      document.getElementById('post-studio').innerHTML = postStudioHtml(selected);
      loadTopicBrief(selected);
      document.getElementById('topic-media-links').innerHTML = mediaSources(selected.topic).map((x) => `<a class="chip" href="${x.url}" target="_blank" rel="noreferrer">${escapeHtml(x.label)}</a>`).join('');
      updateWatchlistButton();
    }
    async function loadData() {
      if (loadInFlight) return;
      loadInFlight = true;
      setSyncStatus('Synkar live-data...');
      try {
        const scopeQuery = `?scope=${encodeURIComponent(marketScope)}`;
        const [summary, recent] = await Promise.all([
          fetchApiJson(`/api/summary${scopeQuery}`),
          fetchApiJson(`/api/recent${scopeQuery}`),
        ]);
        const safeSummary = summary || {};
        const safeRecent = recent || {};
        safeSummary.top_topics = Array.isArray(safeSummary.top_topics) ? safeSummary.top_topics : [];
        safeSummary.hot_topics = Array.isArray(safeSummary.hot_topics) ? safeSummary.hot_topics : [];
        safeSummary.category_movers = Array.isArray(safeSummary.category_movers) ? safeSummary.category_movers : [];
        safeSummary.top_clusters = Array.isArray(safeSummary.top_clusters) ? safeSummary.top_clusters : [];
        safeSummary.reaction_topics = Array.isArray(safeSummary.reaction_topics) ? safeSummary.reaction_topics : [];
        safeSummary.featured_series = Array.isArray(safeSummary.featured_series) ? safeSummary.featured_series : [];
        safeSummary.cluster_multi_series = Array.isArray(safeSummary.cluster_multi_series) ? safeSummary.cluster_multi_series : [];
        safeSummary.backtest = safeSummary.backtest || {};
        safeRecent.items = Array.isArray(safeRecent.items) ? safeRecent.items : [];
        safeRecent.total_new_mentions = Number(safeRecent.total_new_mentions || 0);
        safeRecent.total_fetched_mentions = Number(safeRecent.total_fetched_mentions || 0);
        lastRecent = safeRecent;

      renderTop10(safeSummary);

      const hotItems = filtered(safeSummary.hot_topics || []);
      document.getElementById('hot-topics').innerHTML = hotItems.map((item) => `
        <li>
          <div class="row">
            <div>
              <span class="badge" style="background:${colorFor(item.category)}"></span>
              <span class="topic">${item.topic}</span>
              <span class="source">${item.category}</span>
            </div>
            <div class="row" style="align-items:center;">
              ${canOpenTopic() ? `<a class="secondary-btn" href="${topicLink(item)}">Open topic</a>` : ``}
              <div class="score">${item.total_mentions}</div>
            </div>
          </div>
          <div class="muted">${item.total_mentions} mentions • ${item.source_count} källor med träff • seen ${item.latest_observed_at_human} • published ${item.latest_published_at_human || '-'}</div>
          ${chipsHtml(item)}
          ${item.example_title ? `<div class="muted">${escapeHtml(item.example_title)}</div>` : ''}
        </li>
      `).join('') || '<li class="muted">No hot mentions yet.</li>';

      const maxCategory = Math.max(...safeSummary.category_movers.map((item) => item.total_mentions || 0), 1);
      document.getElementById('categories').innerHTML = safeSummary.category_movers.map((item) => `
        <div class="metric">
          <div style="min-width: 110px;">
            <span class="badge" style="background:${colorFor(item.category)}"></span>
            <strong>${item.category}</strong>
            <div class="muted">${item.top_topic || 'no topic yet'}</div>
          </div>
          <div class="bar" title="${item.total_mentions} mentions">
            <span style="width:${Math.max(6, (item.total_mentions / maxCategory) * 100)}%; background:${colorFor(item.category)}"></span>
          </div>
          <div class="score">${item.total_mentions}</div>
        </div>
      `).join('') || '<div class="muted">No category data yet.</div>';

      document.getElementById('clusters').innerHTML = safeSummary.top_clusters.map((item) => `
        <li>
          <div class="row">
            <div>
              <span class="badge" style="background:${colorFor(item.category)}"></span>
              <span class="topic">${escapeHtml(item.cluster_label)}</span>
              <span class="source">${item.category}</span>
            </div>
            <div class="score">${item.trend_score.toFixed(1)}</div>
          </div>
          <div class="muted">${item.total_mentions} mentions • ${item.topic_count} topics • ${item.samples} samples • score ${item.trend_score.toFixed(1)} / 100</div>
        </li>
      `).join('') || '<li class="muted">No clusters yet.</li>';

      document.getElementById('reactions').innerHTML = filtered(safeSummary.reaction_topics || []).map((item) => {
        const moodColor = item.sentiment_score > 10 ? '#22c55e' : (item.sentiment_score < -10 ? '#ef4444' : '#f59e0b');
        const topicLabel = item.display_topic || item.topic;
        return `
          <li>
            <div class="row">
              <div>
                <span class="badge" style="background:${colorFor(item.category)}"></span>
                <span class="topic">${escapeHtml(topicLabel)}</span>
                <span class="source">${item.category}</span>
              </div>
              <div class="score" style="color:${moodColor}">${item.mood}</div>
            </div>
            <div class="muted">Känsloscore: ${item.sentiment_score} • Reaktionsstyrka: ${item.intensity}/100</div>
            ${item.example_title ? `<div class="muted">Based on: ${escapeHtml(item.example_title)}</div>` : ''}
          </li>
        `;
      }).join('') || '<li class="muted">No reaction data yet.</li>';

      document.getElementById('featured-chart').innerHTML = lineChart(safeSummary.featured_series, '#f59e0b');
      document.getElementById('featured-label').textContent = safeSummary.featured_label || 'No featured series yet.';
      document.getElementById('cluster-chart').innerHTML = multiLineChart(safeSummary.cluster_multi_series || []);
      document.getElementById('cluster-label').textContent = (safeSummary.cluster_multi_series && safeSummary.cluster_multi_series.length)
        ? 'Top 5 clusters (last 6h, local time)'
        : (safeSummary.cluster_label || 'No cluster series yet.');
      lastSummary = safeSummary;

      const backtest = {
        live_alerts_24h: Number(safeSummary.backtest.live_alerts_24h || 0),
        live_alerts_7d: Number(safeSummary.backtest.live_alerts_7d || 0),
        lookback_days: Number(safeSummary.backtest.lookback_days || 7),
        simulated_alerts: Number(safeSummary.backtest.simulated_alerts || 0),
        topics_tested: Number(safeSummary.backtest.topics_tested || 0),
        alert_rate: Number(safeSummary.backtest.alert_rate || 0),
        strongest_category: safeSummary.backtest.strongest_category || 'default',
        strongest_topic: safeSummary.backtest.strongest_topic || '-',
        strongest_score: Number(safeSummary.backtest.strongest_score || 0),
      };
      document.getElementById('backtest').innerHTML = `
        <div class="metric"><div><strong>Live alerts (24h)</strong><div class="muted">Actual Discord alerts sent in the last 24 hours.</div></div><div class="score">${backtest.live_alerts_24h}</div></div>
        <div class="metric"><div><strong>Live alerts (7d)</strong><div class="muted">Actual Discord alerts sent in the last 7 days.</div></div><div class="score">${backtest.live_alerts_7d}</div></div>
        <div class="metric"><div><strong>Simulated alerts</strong><div class="muted">How many alerts the current rules would have produced in the last ${backtest.lookback_days} days.</div></div><div class="score">${backtest.simulated_alerts}</div></div>
        <div class="metric"><div><strong>Topics tested</strong><div class="muted">How many topics existed in the backtest window.</div></div><div class="score">${backtest.topics_tested}</div></div>
        <div class="metric"><div><strong>Alert rate</strong><div class="muted">Simulated alerts divided by topics tested.</div></div><div class="score">${(backtest.alert_rate * 100).toFixed(1)}%</div></div>
        <div class="metric"><div><strong>Strongest topic</strong><div class="muted">${escapeHtml(backtest.strongest_category)}</div></div><div class="score">${escapeHtml(backtest.strongest_topic)}</div></div>
        <div class="metric"><div><strong>Peak score</strong><div class="muted">Highest simulated spike ratio seen in the backtest.</div></div><div class="score">${backtest.strongest_score.toFixed(2)}</div></div>
      `;

      const hasNewInRecent = safeRecent.items.some((item) => item.new_mentions > 0);
      const staleSuffix = (safeSummary.data_mode || '').startsWith('fallback_')
        ? ` • scanner is stale, latest snapshot: ${safeSummary.latest_known_observed_at_human || 'unknown'}`
        : '';
      document.getElementById('recent-status').textContent = hasNewInRecent
        ? `New matches in recent rows: ${safeRecent.total_new_mentions} / ${safeRecent.total_fetched_mentions} fetched`
        : `No new items in the most recent cycle(s). Seen before or no fresh matches. (${safeRecent.total_new_mentions} / ${safeRecent.total_fetched_mentions})${staleSuffix}`;

      document.getElementById('recent').innerHTML = safeRecent.items.map((item) => `
        <li>
          <div class="row">
            <div>
              <span class="badge" style="background:${colorFor(item.category)}"></span>
              <span class="topic">${item.topic}</span>
              <span class="source">${item.source}</span>
            </div>
            <div class="score">${item.new_mentions} / ${item.fetched_mentions}</div>
          </div>
          <div class="muted">${item.observed_at_human} • new/fetched</div>
        </li>
      `).join('') || '<li class="muted">No data yet.</li>';
      renderWatchlist();
      applyViewMode(safeSummary);
      const lastKnown = safeSummary.latest_known_observed_at_human || safeSummary.latest_observed_at_human || '';
      if (lastKnown) {
        setSyncStatus(`Live • senast uppdaterad ${lastKnown}`);
      } else {
        setSyncStatus('Live • uppdaterad');
      }
      } catch (err) {
        console.error('loadData failed:', err);
        const message = `Could not load live data (${escapeHtml(String(err && err.message ? err.message : err))}).`;
        if (lastSummary) {
          setSyncStatus(`Tillfälligt sync-fel, visar senaste data. (${String(err && err.message ? err.message : err)})`, true);
          return;
        }
        ['daily-topics', 'hot-topics', 'categories', 'clusters', 'reactions', 'recent', 'backtest'].forEach((id) => {
          const el = document.getElementById(id);
          if (el) el.innerHTML = `<li class="muted">${message}</li>`;
        });
        const status = document.getElementById('recent-status');
        if (status) status.textContent = message;
        setSyncStatus('Kunde inte ladda live-data ännu.', true);
      } finally {
        loadInFlight = false;
      }
    }
    async function ensureAuth() {
      const overlay = document.getElementById('login-overlay');
      try {
        const me = await fetchApiJson('/api/me');
        if (me && me.authenticated) {
          userRole = (me.role || 'start').toLowerCase();
          applyRoleUI();
          overlay.style.display = 'none';
          return true;
        }
        userRole = 'lite';
        applyRoleUI();
        overlay.style.display = 'none';
        return true;
      } catch (_err) {}
      userRole = 'lite';
      applyRoleUI();
      overlay.style.display = 'none';
      return true;
    }
    async function doLogin() {
      const username = (document.getElementById('login-username').value || '').trim();
      const password = (document.getElementById('login-password').value || '').trim();
      const status = document.getElementById('login-status');
      status.textContent = 'Loggar in...';
      try {
        const res = await fetch('/api/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ username, password }),
        });
        const data = await res.json();
        if (!res.ok || !data.ok) {
          status.textContent = data.error || 'Fel login';
          return;
        }
        userRole = (data.role || 'start').toLowerCase();
        applyRoleUI();
        document.getElementById('login-overlay').style.display = 'none';
        status.textContent = '';
        loadData();
      } catch (_err) {
        status.textContent = 'Kunde inte logga in';
      }
    }
    async function doLogout() {
      if (userRole === 'lite') {
        const status = document.getElementById('login-status');
        if (status) status.textContent = '';
        document.getElementById('login-overlay').style.display = 'flex';
        return;
      }
      try {
        await fetch('/api/logout', { method: 'POST', credentials: 'include' });
      } catch (_err) {}
      userRole = 'lite';
      applyRoleUI();
      const status = document.getElementById('login-status');
      if (status) status.textContent = '';
      const pw = document.getElementById('login-password');
      if (pw) pw.value = '';
      document.getElementById('login-overlay').style.display = 'none';
      loadData();
    }
    function forceRefresh() {
      const url = new URL(window.location.href);
      url.searchParams.set('r', String(Date.now()));
      window.location.replace(url.toString());
    }
    async function askPostAI() {
      const input = document.getElementById('post-ai-question');
      const box = document.getElementById('post-ai-answer');
      const q = ((input && input.value) || '').trim();
      box.textContent = 'Tänker...';
      try {
        const scope = `scope=${encodeURIComponent(marketScope)}`;
        const question = `question=${encodeURIComponent(q || 'Vad är bäst att posta just nu?')}`;
        const data = await fetchApiJson(`/api/post_ai?${scope}&${question}`);
        const ideas = Array.isArray(data.ideas) ? data.ideas : [];
        const ideasHtml = ideas.map((item, idx) => (
          `<div style="margin-top:8px;"><strong>${idx + 1}. ${escapeHtml(item.topic || '')}</strong><div class="muted">${escapeHtml(item.hook || '')}</div></div>`
        )).join('');
        box.innerHTML = `<div>${escapeHtml(data.answer || 'Inget svar just nu.')}</div>${ideasHtml}`;
      } catch (_err) {
        box.textContent = 'Kunde inte hämta AI-svar just nu. Testa igen om några sekunder.';
      }
    }
    function renderMediaPage(summary) {
      const params = new URLSearchParams(window.location.search || '');
      const requestedTopic = (params.get('topic') || '').trim();
      const fallbackTopic = (summary.top_topics && summary.top_topics.length)
        ? summary.top_topics[0].topic
        : ((summary.hot_topics && summary.hot_topics.length) ? summary.hot_topics[0].topic : 'trend topic');
      const selectedTopic = requestedTopic || fallbackTopic;

      document.getElementById('media-selected-topic').textContent = selectedTopic;
      const links = mediaSources(selectedTopic);
      document.getElementById('media-links').innerHTML = links.map((item) => `
        <a class="media-card" href="${item.url}" target="_blank" rel="noreferrer">
          <div style="font-weight:600; margin-bottom:6px;">${escapeHtml(item.label)}</div>
          <div class="muted">${escapeHtml(item.description)}</div>
        </a>
      `).join('');

      const chips = [...(summary.top_topics || []), ...(summary.hot_topics || [])]
        .filter((item, idx, arr) => arr.findIndex((other) => other.topic === item.topic) === idx)
        .slice(0, 20);
      document.getElementById('media-topic-chips').innerHTML = chips.map((item) => `
        <a class="chip" href="${mediaPageLink(item.topic)}">${escapeHtml(item.topic)}</a>
      `).join('');
      loadMediaLibrary(selectedTopic);
    }
    async function loadMediaLibrary(topic) {
      const imageTarget = document.getElementById('media-image-grid');
      const videoTarget = document.getElementById('media-video-grid');
      imageTarget.innerHTML = '<div class="muted">Laddar bilder...</div>';
      videoTarget.innerHTML = '<div class="muted">Laddar videor...</div>';
      try {
        const data = await fetchApiJson(`/api/media?topic=${encodeURIComponent(topic || '')}`);
        const imageCards = (data.images || []).map((item) => `
          <a class="media-image-card" href="${item.full_image || item.url}" target="_blank" rel="noreferrer">
            <img src="${item.thumbnail}" alt="${escapeHtml(item.title || 'Image')}" loading="lazy" />
            <div class="label">${escapeHtml(item.title || 'Image')}</div>
            <div class="sub">Google News</div>
          </a>
        `);
        imageTarget.innerHTML = imageCards.length
          ? imageCards.join('')
          : '<div class="muted">Inga relevanta bilder hittades för ämnet just nu.</div>';

        const videoCards = (data.videos || []).map((item) => `
          <a class="media-image-card" href="${item.url}" target="_blank" rel="noreferrer">
            <img src="${item.thumbnail}" alt="${escapeHtml(item.title || 'Video')}" loading="lazy" />
            <div class="label">${escapeHtml(item.title || 'Video')}</div>
            <div class="sub">Google News</div>
          </a>
        `);
        videoTarget.innerHTML = videoCards.length
          ? videoCards.join('')
          : '<div class="muted">Inga relevanta videor hittades för ämnet just nu.</div>';
      } catch (err) {
        imageTarget.innerHTML = '<div class="muted">Kunde inte hämta bilder just nu.</div>';
        videoTarget.innerHTML = '<div class="muted">Kunde inte hämta videor just nu.</div>';
      }
    }
    function applyViewMode(summary) {
      const params = new URLSearchParams(window.location.search || '');
      const requestedView = (params.get('view') || '').toLowerCase();
      const isProOrHigher = (ROLE_RANK[userRole] || 0) >= (ROLE_RANK.pro || 1);
      const isStartOrHigher = (ROLE_RANK[userRole] || 0) >= (ROLE_RANK.start || 1);
      const mediaMode = requestedView === 'media' && isProOrHigher;
      const topicMode = requestedView === 'topic' && isStartOrHigher;
      const dashboardPage = document.getElementById('dashboard-page');
      const mediaPage = document.getElementById('media-page');
      const topicPage = document.getElementById('topic-page');
      const navDashboard = document.getElementById('nav-dashboard');
      const navMedia = document.getElementById('nav-media');
      const navTopic = document.getElementById('nav-topic');
      if (!isProOrHigher && requestedView === 'media') {
        const clean = new URL(window.location.href);
        clean.searchParams.delete('view');
        clean.searchParams.delete('topic');
        window.history.replaceState({}, '', clean.toString());
      }
      if (!isStartOrHigher && requestedView === 'topic') {
        const clean = new URL(window.location.href);
        clean.searchParams.delete('view');
        clean.searchParams.delete('key');
        window.history.replaceState({}, '', clean.toString());
      }
      if (mediaMode) {
        dashboardPage.style.display = 'none';
        topicPage.style.display = 'none';
        mediaPage.style.display = 'grid';
        renderMediaPage(summary);
        navDashboard.classList.remove('active');
        navTopic.classList.remove('active');
        navMedia.classList.add('active');
      } else if (topicMode) {
        dashboardPage.style.display = 'none';
        mediaPage.style.display = 'none';
        topicPage.style.display = 'grid';
        renderTopicPage(summary);
        navDashboard.classList.remove('active');
        navMedia.classList.remove('active');
        navTopic.classList.add('active');
      } else {
        dashboardPage.style.display = 'grid';
        mediaPage.style.display = 'none';
        topicPage.style.display = 'none';
        navMedia.classList.remove('active');
        navTopic.classList.remove('active');
        navDashboard.classList.add('active');
      }
    }
    applyScopeButtons();
    initTheme();
    initCookieConsent();
    document.getElementById('theme-toggle').addEventListener('click', toggleTheme);
    document.getElementById('refresh-btn').addEventListener('click', forceRefresh);
    document.getElementById('logout-btn').addEventListener('click', doLogout);
    document.getElementById('nav-home').addEventListener('click', (e) => {
      e.preventDefault();
      window.location.href = 'https://trendbot.se';
    });
    document.getElementById('login-close').addEventListener('click', () => {
      const status = document.getElementById('login-status');
      if (status) status.textContent = '';
      document.getElementById('login-overlay').style.display = 'none';
    });
    applyRoleUI();
    document.getElementById('login-submit').addEventListener('click', doLogin);
    document.getElementById('login-password').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        doLogin();
      }
    });
    document.getElementById('post-ai-ask').addEventListener('click', askPostAI);
    document.getElementById('post-ai-question').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        askPostAI();
      }
    });
    ensureAuth().then(() => loadData());
    setInterval(loadData, 15000);
  </script>
</body>
</html>"""
    return template.replace("__BOOTSTRAP_DATA__", bootstrap_json)


class _DashboardHandler(BaseHTTPRequestHandler):
    storage: Storage
    settings: dict[str, Any]

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/privacy"):
            self._send_html(_render_privacy_page())
            return
        if self.path.startswith("/cookies"):
            self._send_html(_render_cookie_page())
            return
        if self.path.startswith("/legal/dsr"):
            self._send_html(_render_dsr_page())
            return
        if self.path.startswith("/legal/register"):
            self._send_html(_render_register_page())
            return
        if self.path.startswith("/api/health"):
            self._send_json({"ok": True, "status": "healthy"})
            return
        if self.path.startswith("/api/me"):
            session = self._session_info()
            role = (session or {}).get("role")
            self._send_json({"authenticated": bool(role), "role": role or "lite"})
            return
        if self.path.startswith("/api/login"):
            self._send_json({"ok": False, "error": "Use POST for login"}, status=405)
            return
        is_public_api = any(
            self.path.startswith(prefix)
            for prefix in ("/api/summary", "/api/recent", "/api/media", "/api/brief")
        )
        if self.path.startswith("/api/") and not is_public_api and not self._is_authenticated():
            self._send_json({"ok": False, "error": "Unauthorized"}, status=401)
            return
        if self.path.startswith("/api/summary"):
            scope = parse_qs(urlparse(self.path).query).get("scope", [""])[0].strip().lower()
            market_scope = scope if scope in {"sweden", "global"} else None
            self._send_json(self._summary_payload(market_scope))
            return
        if self.path.startswith("/api/recent"):
            scope = parse_qs(urlparse(self.path).query).get("scope", [""])[0].strip().lower()
            market_scope = scope if scope in {"sweden", "global"} else None
            self._send_json(self._recent_payload(market_scope))
            return
        if self.path.startswith("/api/media"):
            topic = parse_qs(urlparse(self.path).query).get("topic", [""])[0]
            self._send_json(_media_payload(topic))
            return
        if self.path.startswith("/api/brief"):
            topic = parse_qs(urlparse(self.path).query).get("topic", [""])[0]
            self._send_json(_topic_brief_payload(topic))
            return
        if self.path.startswith("/api/post_ai"):
            role = self._current_role()
            allowed, remaining = self._consume_post_ai_quota(role)
            if not allowed:
                self._send_json(
                    {
                        "ok": False,
                        "error": "Daily limit reached for your plan.",
                        "role": role,
                        "remaining": 0,
                    },
                    status=429,
                )
                return
            params = parse_qs(urlparse(self.path).query)
            topic_question = params.get("question", [""])[0]
            scope = params.get("scope", [""])[0].strip().lower()
            market_scope = scope if scope in {"sweden", "global"} else None
            payload = _post_ai_payload(self.storage, self.settings, topic_question, market_scope)
            payload["role"] = role
            payload["remaining"] = remaining
            self._send_json(payload)
            return
        self._send_html(
            _render_index(
                {
                    "optional_tracking_enabled": bool(self.settings.get("optional_tracking_enabled", False)),
                }
            )
        )

    def do_POST(self) -> None:  # noqa: N802
        if self.path.startswith("/api/login"):
            raw = self._read_json_body()
            username = str(raw.get("username", "")).strip().lower()
            password = str(raw.get("password", "")).strip()
            creds = self._auth_credentials()
            expected = creds.get(username, "")
            if not expected or not self._verify_password(password, expected):
                self._send_json({"ok": False, "error": "Fel användarnamn eller lösenord"}, status=401)
                return
            token = secrets.token_urlsafe(24)
            _SESSION_STORE[token] = {"role": username, "created_at": int(time.time())}
            self._send_json(
                {"ok": True, "role": username},
                headers={"Set-Cookie": f"trendbot_session={token}; Path=/; HttpOnly; SameSite=Lax"},
            )
            return
        if self.path.startswith("/api/logout"):
            token = self._session_token()
            if token:
                _SESSION_STORE.pop(token, None)
            self._send_json(
                {"ok": True},
                headers={"Set-Cookie": "trendbot_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax"},
            )
            return
        self._send_json({"ok": False, "error": "Not found"}, status=404)

    def do_HEAD(self) -> None:  # noqa: N802
        if (
            self.path.startswith("/privacy")
            or self.path.startswith("/cookies")
            or self.path.startswith("/legal/dsr")
            or self.path.startswith("/legal/register")
        ):
            body = b""
            self._send_headers("text/html; charset=utf-8", len(body))
            return
        if self.path.startswith("/api/health"):
            self._send_headers("application/json; charset=utf-8", len(b'{"ok":true}'))
            return
        is_public_api = any(
            self.path.startswith(prefix)
            for prefix in ("/api/me", "/api/summary", "/api/recent", "/api/media", "/api/brief")
        )
        if self.path.startswith("/api/") and not is_public_api and not self._is_authenticated():
            self._send_headers("application/json; charset=utf-8", 0, status=401)
            return
        if self.path.startswith("/api/summary"):
            self._send_headers("application/json; charset=utf-8", len(json.dumps(self._summary_payload()).encode("utf-8")))
            return
        if self.path.startswith("/api/recent"):
            self._send_headers("application/json; charset=utf-8", len(json.dumps(self._recent_payload()).encode("utf-8")))
            return
        if self.path.startswith("/api/media"):
            topic = parse_qs(urlparse(self.path).query).get("topic", [""])[0]
            self._send_headers("application/json; charset=utf-8", len(json.dumps(_media_payload(topic)).encode("utf-8")))
            return
        if self.path.startswith("/api/brief"):
            topic = parse_qs(urlparse(self.path).query).get("topic", [""])[0]
            self._send_headers("application/json; charset=utf-8", len(json.dumps(_topic_brief_payload(topic)).encode("utf-8")))
            return
        if self.path.startswith("/api/post_ai"):
            params = parse_qs(urlparse(self.path).query)
            topic_question = params.get("question", [""])[0]
            scope = params.get("scope", [""])[0].strip().lower()
            market_scope = scope if scope in {"sweden", "global"} else None
            payload = _post_ai_payload(self.storage, self.settings, topic_question, market_scope)
            self._send_headers("application/json; charset=utf-8", len(json.dumps(payload).encode("utf-8")))
            return
        body = _render_index(
            {"optional_tracking_enabled": bool(self.settings.get("optional_tracking_enabled", False))}
        ).encode("utf-8")
        self._send_headers("text/html; charset=utf-8", len(body))

    def _summary_payload(self, market_scope: str | None = None) -> dict[str, Any]:
        if self.settings.get("swedish_only_mode"):
            if self._current_role() == "lite":
                market_scope = "sweden"
            elif market_scope == "global":
                market_scope = "sweden"
        return _summary_payload(self.storage, self.settings, market_scope)

    def _recent_payload(self, market_scope: str | None = None) -> dict[str, Any]:
        if self.settings.get("swedish_only_mode"):
            if self._current_role() == "lite":
                market_scope = "sweden"
            elif market_scope == "global":
                market_scope = "sweden"
        return _recent_payload(self.storage, market_scope)

    def _auth_credentials(self) -> dict[str, str]:
        return {
            "admin": (self.settings.get("dashboard_admin_password") or "").strip(),
            "start": (self.settings.get("dashboard_start_password") or "").strip(),
            "pro": (self.settings.get("dashboard_pro_password") or "").strip(),
        }

    def _verify_password(self, provided: str, stored: str) -> bool:
        # Strict format only:
        # pbkdf2_sha256$<iterations>$<salt>$<hex_digest>
        if not stored.startswith("pbkdf2_sha256$"):
            return False
        try:
            _, iter_s, salt, digest_hex = stored.split("$", 3)
            iterations = int(iter_s)
            calculated = hashlib.pbkdf2_hmac(
                "sha256",
                provided.encode("utf-8"),
                salt.encode("utf-8"),
                iterations,
            ).hex()
            return hmac.compare_digest(calculated, digest_hex)
        except Exception:
            return False

    def _session_token(self) -> str:
        cookie = self.headers.get("Cookie", "")
        for part in cookie.split(";"):
            part = part.strip()
            if part.startswith("trendbot_session="):
                return part.split("=", 1)[1].strip()
        return ""

    def _session_info(self) -> dict[str, Any] | None:
        token = self._session_token()
        if not token:
            return None
        return _SESSION_STORE.get(token)

    def _current_role(self) -> str:
        session = self._session_info() or {}
        role = str(session.get("role", "")).lower()
        if role in {"admin", "pro", "start"}:
            return role
        return "lite"

    def _post_ai_limit_for_role(self, role: str) -> int:
        if role == "admin":
            return 10_000_000
        if role == "pro":
            return 5
        return 1

    def _consume_post_ai_quota(self, role: str) -> tuple[bool, int]:
        if role == "admin":
            return True, 10_000_000
        local_day = time.strftime("%Y-%m-%d", time.localtime())
        state_key = f"post_ai_usage:{local_day}:{role}"
        used_raw = self.storage.get_state(state_key) or "0"
        try:
            used = int(used_raw)
        except ValueError:
            used = 0
        limit = self._post_ai_limit_for_role(role)
        if used >= limit:
            return False, 0
        used += 1
        self.storage.set_state(state_key, str(used))
        remaining = max(0, limit - used)
        return True, remaining

    def _is_authenticated(self) -> bool:
        session = self._session_info()
        return bool(session and session.get("role") in {"admin", "start", "pro"})

    def _read_json_body(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
        except ValueError:
            length = 0
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            data = json.loads(raw.decode("utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _send_json(self, payload: dict[str, Any], status: int = 200, headers: dict[str, str] | None = None) -> None:
        data = json.dumps(payload).encode("utf-8")
        self._send_headers("application/json; charset=utf-8", len(data), status=status, headers=headers)
        self.wfile.write(data)

    def _send_headers(self, content_type: str, content_length: int, status: int = 200, headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(content_length))
        if headers:
            for key, value in headers.items():
                self.send_header(key, value)
        self.end_headers()

    def _send_html(self, body: str) -> None:
        data = body.encode("utf-8")
        self._send_headers("text/html; charset=utf-8", len(data))
        self.wfile.write(data)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return


class DashboardServer:
    def __init__(
        self,
        storage: Storage,
        host: str = "127.0.0.1",
        port: int = 8000,
        settings: dict[str, Any] | None = None,
    ) -> None:
        self.storage = storage
        self.host = host
        self.port = port
        self.settings = settings or {}
        handler = type(
            "TrendBotDashboardHandler",
            (_DashboardHandler,),
            {"storage": storage, "settings": self.settings},
        )
        self._server = ThreadingHTTPServer((host, port), handler)
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


def write_snapshot_file(storage: Storage, path: str, settings: dict[str, Any] | None = None) -> None:
    snapshot = {
        "summary": _summary_payload(storage, settings or {}, "sweden"),
        "recent": _recent_payload(storage, "sweden"),
    }
    html = _render_index(snapshot)
    Path(path).write_text(html, encoding="utf-8")
