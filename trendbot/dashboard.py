from __future__ import annotations

import html
import json
import re
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


def _clean_example_title(title: str) -> str:
    cleaned = (title or "").strip()
    if not cleaned:
        return ""
    if " - " in cleaned:
        cleaned = cleaned.split(" - ", 1)[0].strip()
    if "|" in cleaned:
        cleaned = cleaned.split("|", 1)[0].strip()
    if ":" in cleaned:
        prefix, suffix = cleaned.split(":", 1)
        if len(prefix.strip()) <= 18 and suffix.strip():
            cleaned = suffix.strip()
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
        and len(label.split()) >= 3
        and not _looks_dateish(label)
        and not _is_genericish_label(label)
    ):
        return label
    fallback = _clean_example_title(example_title)
    if fallback and not _looks_dateish(fallback):
        return fallback
    raw_example = (example_title or "").strip()
    if "|" in raw_example:
        raw_example = raw_example.split("|", 1)[0].strip()
    if " - " in raw_example:
        raw_example = raw_example.split(" - ", 1)[0].strip()
    raw_example = re.sub(r"\s+", " ", raw_example).strip()
    if raw_example and len(raw_example.split()) >= 2 and not _looks_dateish(raw_example):
        return raw_example
    if label and not _looks_dateish(label):
        return label
    return "Trending story"


def _topic_reaction(topic: str, example_title: str) -> dict[str, Any]:
    text = f"{topic} {example_title}".lower()
    positive = sum(1 for w in POSITIVE_REACTION_WORDS if w in text)
    negative = sum(1 for w in NEGATIVE_REACTION_WORDS if w in text)
    strong = sum(1 for w in STRONG_REACTION_WORDS if w in text)
    sentiment_score = max(-100, min(100, (positive - negative) * 18))
    if sentiment_score > 12:
        mood = "Mest positiv"
    elif sentiment_score < -12:
        mood = "Mest negativ"
    else:
        mood = "Blandad reaktion"
    intensity = min(100, max(20, (strong * 22) + (negative * 8) + (positive * 6)))
    return {
        "mood": mood,
        "sentiment_score": sentiment_score,
        "intensity": intensity,
    }


def _summary_payload(storage: Storage, settings: dict[str, Any]) -> dict[str, Any]:
    from datetime import datetime, timezone

    blocked_terms = [str(t).strip().lower() for t in (settings.get("blocked_terms") or []) if str(t).strip()]

    def _is_blocked(*values: str) -> bool:
        if not blocked_terms:
            return False
        text = " ".join((value or "") for value in values).lower()
        return any(term in text for term in blocked_terms)

    now = int(datetime.now(tz=timezone.utc).timestamp())
    min_daily_mentions = int(settings.get("daily_top_min_mentions", 3))
    top_topic_candidates = [
        row
        for row in storage.top_topics_since(now - 86400, 80, min_total_mentions=min_daily_mentions)
        if not _is_blocked(row.topic, row.cluster_label, row.example_title)
    ]
    hot_topics = [
        row
        for row in storage.top_topics_since(now - 3600, 40, min_total_mentions=1)
        if not _is_blocked(row.topic, row.cluster_label, row.example_title)
    ][:10]
    sticky_key = "dashboard:sticky_top10:v1"
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

    def _sticky_score(item) -> float:
        base = float(item.total_mentions)
        idx = previous_rank.get(item.cluster_key)
        if idx is None:
            return base
        # Hysteresis: previously ranked items get a modest bonus, but can still drop if clearly weaker.
        return base + 0.9 + max(0.0, (10 - idx) * 0.06)

    top_topics = sorted(
        top_topic_candidates,
        key=lambda item: (_sticky_score(item), item.latest_observed_at, item.trend_score),
        reverse=True,
    )[:10]
    storage.set_state(sticky_key, json.dumps([item.cluster_key for item in top_topics]))
    top_categories = storage.top_categories_since(now - 86400, 8)
    top_clusters = [
        row
        for row in storage.top_clusters_since(now - 86400, 30)
        if not _is_blocked(row.cluster_label, row.example_title)
    ][:10]
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
    return {
        "top_topics": [
            {
                "topic": _series_label(row.cluster_label, row.example_title),
                "cluster_key": row.cluster_key,
                "example_title": row.example_title,
                "total_mentions": row.total_mentions,
                "samples": row.samples,
                "latest_observed_at": row.latest_observed_at,
                "latest_observed_at_human": _format_ts(row.latest_observed_at),
                "trend_score": row.trend_score,
                "category": row.category,
                "cluster_label": row.cluster_label,
                "source_count": row.source_count,
                "link": f"https://news.google.com/search?q={quote_plus(_series_label(row.cluster_label, row.example_title))}",
            }
            for row in top_topics
        ],
        "hot_topics": [
            {
                "topic": _series_label(row.cluster_label, row.example_title),
                "cluster_key": row.cluster_key,
                "example_title": row.example_title,
                "total_mentions": row.total_mentions,
                "samples": row.samples,
                "latest_observed_at": row.latest_observed_at,
                "latest_observed_at_human": _format_ts(row.latest_observed_at),
                "trend_score": row.trend_score,
                "category": row.category,
                "cluster_label": row.cluster_label,
                "source_count": row.source_count,
                "link": f"https://news.google.com/search?q={quote_plus(_series_label(row.cluster_label, row.example_title))}",
            }
            for row in hot_topics
        ],
        "reaction_topics": [
            {
                "topic": row.topic,
                "display_topic": _series_label(row.cluster_label, row.example_title),
                "category": row.category,
                "example_title": row.example_title,
                **_topic_reaction(_series_label(row.cluster_label, row.example_title), row.example_title),
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
                "cluster_label": _series_label(row.cluster_label, row.example_title),
                "category": row.category,
                "total_mentions": row.total_mentions,
                "samples": row.samples,
                "latest_observed_at": row.latest_observed_at,
                "topic_count": row.topic_count,
                "trend_score": row.trend_score,
                "example_title": row.example_title,
            }
            for row in top_clusters
        ],
        "featured_label": (
            _series_label(top_clusters[0].cluster_label, top_clusters[0].example_title)
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
        "cluster_label": _series_label(top_clusters[0].cluster_label, top_clusters[0].example_title) if top_clusters else "No cluster yet.",
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
    }


def _recent_payload(storage: Storage) -> dict[str, Any]:
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
      font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: radial-gradient(circle at top, #1e293b 0, #0f172a 55%);
      color: var(--text);
    }
    header {
      padding: 20px 24px 12px;
    }
    .topbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 10px;
    }
    .nav-links {
      display: inline-flex;
      align-items: center;
      gap: 8px;
    }
    .nav-link {
      border: 1px solid rgba(148, 163, 184, 0.26);
      background: rgba(15, 23, 42, 0.9);
      color: #e2e8f0;
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
    h1 { margin: 0; font-size: 28px; }
    p { color: var(--muted); margin: 8px 0 0; }
    main { padding: 0 24px 32px; display: grid; gap: 18px; }
    .grid { display: grid; gap: 18px; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); }
    .grid.wide { grid-template-columns: repeat(auto-fit, minmax(380px, 1fr)); }
    .card {
      background: rgba(15, 23, 42, 0.82);
      border: 1px solid rgba(148, 163, 184, 0.18);
      border-radius: 18px;
      padding: 18px;
      box-shadow: 0 20px 60px rgba(0,0,0,.25);
      backdrop-filter: blur(12px);
    }
    h2 { margin: 0 0 12px; font-size: 18px; }
    ol, ul { margin: 0; padding-left: 20px; }
    li { margin: 8px 0; }
    .pill {
      display: inline-block;
      padding: 4px 10px;
      border-radius: 999px;
      background: rgba(245, 158, 11, 0.12);
      color: #fbbf24;
      font-size: 12px;
      margin-left: 8px;
    }
    .muted { color: var(--muted); font-size: 13px; }
    .row { display: flex; justify-content: space-between; gap: 12px; }
    .topic {
      font-weight: 600;
    }
    .score { color: #fbbf24; font-variant-numeric: tabular-nums; }
    .source { color: #60a5fa; font-size: 12px; }
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
      color: #cbd5e1;
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
      border: 1px solid rgba(148, 163, 184, 0.26);
      background: rgba(15, 23, 42, 0.9);
      color: #e2e8f0;
      border-radius: 10px;
      padding: 8px 10px;
      font-size: 13px;
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
    a { color: #93c5fd; text-decoration: none; }
    a:hover { text-decoration: underline; }
    code { background: rgba(148,163,184,.12); padding: 2px 6px; border-radius: 6px; }
  </style>
</head>
<body>
  <header>
    <div class="topbar">
      <h1>TrendBot Dashboard</h1>
      <nav class="nav-links">
        <a id="nav-dashboard" class="nav-link" href="?">Dashboard</a>
        <a id="nav-media" class="nav-link" href="?view=media">Bilder</a>
      </nav>
    </div>
    <p>Live overview of the strongest topics and the latest observations.</p>
  </header>
  <main id="dashboard-page">
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
      <section class="card">
        <h2>Category Movers <span class="pill">top categories</span></h2>
        <div id="categories"><div class="muted">Loading...</div></div>
      </section>
      <section class="card">
        <h2>Topic Clusters <span class="pill">clustered stories</span></h2>
        <ul id="clusters"><li class="muted">Loading...</li></ul>
      </section>
      <section class="card">
        <h2>Vad Folk Tycker <span class="pill">känsla per ämne</span></h2>
        <ul id="reactions"><li class="muted">Loading...</li></ul>
      </section>
    </div>
    <div class="grid wide">
      <section class="card">
        <h2>Trend Graphs</h2>
        <div class="chart" id="featured-chart"></div>
        <p class="muted" id="featured-label">Loading...</p>
      </section>
      <section class="card">
        <h2>Backtest Snapshot</h2>
        <div id="backtest"><div class="muted">Loading...</div></div>
      </section>
    </div>
    <div class="grid wide">
      <section class="card">
        <h2>Recent Observations</h2>
        <p class="muted" id="recent-status">Loading...</p>
        <ul id="recent"><li class="muted">Loading...</li></ul>
      </section>
      <section class="card">
        <h2>Daily Series</h2>
        <div class="chart" id="cluster-chart"></div>
        <p class="muted" id="cluster-label">Loading...</p>
      </section>
    </div>
    <section class="card">
      <h2>Tips</h2>
      <p class="muted">Open the Discord alerts for sharper context, or use the JSON endpoints at <code>/api/summary</code> and <code>/api/recent</code>.</p>
    </section>
    <section class="card">
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
  <script>
    const BOOTSTRAP_DATA = __BOOTSTRAP_DATA__;
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
    function renderTop10(summary) {
      const selectEl = document.getElementById('top10-select');
      const moreBtn = document.getElementById('top10-more');
      const focusEl = document.getElementById('top10-focus');
      const listEl = document.getElementById('top10');
      const allItems = summary.top_topics || [];

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
      focusEl.innerHTML = `
        <strong>${escapeHtml(selected.topic)}</strong>
        <span class="source">${selected.category}</span>
        • ${selected.total_mentions} mentions • score ${selected.trend_score.toFixed(1)} / 100
      `;

      listEl.innerHTML = visibleItems.map((item) => `
        <li>
          <div class="row">
            <div>
              <span class="badge" style="background:${colorFor(item.category)}"></span>
              <span class="topic">${item.topic}</span>
              <span class="source">${item.category}</span>
            </div>
            <div class="score">${item.trend_score.toFixed(1)}</div>
          </div>
          <div class="muted">${item.total_mentions} mentions across ${item.samples} samples • ${item.source_count} sources • latest ${item.latest_observed_at_human}</div>
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
    async function loadData() {
      let summary;
      let recent;
      if (BOOTSTRAP_DATA.summary && BOOTSTRAP_DATA.recent) {
        summary = BOOTSTRAP_DATA.summary;
        recent = BOOTSTRAP_DATA.recent;
      } else {
        const [summaryRes, recentRes] = await Promise.all([
          fetch('/api/summary'),
          fetch('/api/recent'),
        ]);
        summary = await summaryRes.json();
        recent = await recentRes.json();
      }

      renderTop10(summary);

      document.getElementById('hot-topics').innerHTML = summary.hot_topics.map((item) => `
        <li>
          <div class="row">
            <div>
              <span class="badge" style="background:${colorFor(item.category)}"></span>
              <span class="topic">${item.topic}</span>
              <span class="source">${item.category}</span>
            </div>
            <div class="score">${item.total_mentions}</div>
          </div>
          <div class="muted">${item.total_mentions} mentions • ${item.source_count} sources • latest ${item.latest_observed_at_human}</div>
          ${item.example_title ? `<div class="muted">${escapeHtml(item.example_title)}</div>` : ''}
        </li>
      `).join('') || '<li class="muted">No hot mentions yet.</li>';

      const maxCategory = Math.max(...summary.category_movers.map((item) => item.total_mentions || 0), 1);
      document.getElementById('categories').innerHTML = summary.category_movers.map((item) => `
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

      document.getElementById('clusters').innerHTML = summary.top_clusters.map((item) => `
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

      document.getElementById('reactions').innerHTML = (summary.reaction_topics || []).map((item) => {
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

      document.getElementById('featured-chart').innerHTML = lineChart(summary.featured_series, '#f59e0b');
      document.getElementById('featured-label').textContent = summary.featured_label || 'No featured series yet.';
      document.getElementById('cluster-chart').innerHTML = multiLineChart(summary.cluster_multi_series || []);
      document.getElementById('cluster-label').textContent = (summary.cluster_multi_series && summary.cluster_multi_series.length)
        ? 'Top 5 clusters (last 6h, local time)'
        : (summary.cluster_label || 'No cluster series yet.');
      lastSummary = summary;

      document.getElementById('backtest').innerHTML = `
        <div class="metric"><div><strong>Live alerts (24h)</strong><div class="muted">Actual Discord alerts sent in the last 24 hours.</div></div><div class="score">${summary.backtest.live_alerts_24h}</div></div>
        <div class="metric"><div><strong>Live alerts (7d)</strong><div class="muted">Actual Discord alerts sent in the last 7 days.</div></div><div class="score">${summary.backtest.live_alerts_7d}</div></div>
        <div class="metric"><div><strong>Simulated alerts</strong><div class="muted">How many alerts the current rules would have produced in the last ${summary.backtest.lookback_days} days.</div></div><div class="score">${summary.backtest.simulated_alerts}</div></div>
        <div class="metric"><div><strong>Topics tested</strong><div class="muted">How many topics existed in the backtest window.</div></div><div class="score">${summary.backtest.topics_tested}</div></div>
        <div class="metric"><div><strong>Alert rate</strong><div class="muted">Simulated alerts divided by topics tested.</div></div><div class="score">${(summary.backtest.alert_rate * 100).toFixed(1)}%</div></div>
        <div class="metric"><div><strong>Strongest topic</strong><div class="muted">${escapeHtml(summary.backtest.strongest_category || 'default')}</div></div><div class="score">${escapeHtml(summary.backtest.strongest_topic || '-')}</div></div>
        <div class="metric"><div><strong>Peak score</strong><div class="muted">Highest simulated spike ratio seen in the backtest.</div></div><div class="score">${summary.backtest.strongest_score.toFixed(2)}</div></div>
      `;

      const hasNewInRecent = recent.items.some((item) => item.new_mentions > 0);
      document.getElementById('recent-status').textContent = hasNewInRecent
        ? `New matches in recent rows: ${recent.total_new_mentions} / ${recent.total_fetched_mentions} fetched`
        : `No new items in the most recent cycle(s). Seen before or no fresh matches. (${recent.total_new_mentions} / ${recent.total_fetched_mentions})`;

      document.getElementById('recent').innerHTML = recent.items.map((item) => `
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
      applyViewMode(summary);
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
        const res = await fetch(`/api/media?topic=${encodeURIComponent(topic || '')}`);
        const data = await res.json();
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
      const mediaMode = params.get('view') === 'media';
      const dashboardPage = document.getElementById('dashboard-page');
      const mediaPage = document.getElementById('media-page');
      const navDashboard = document.getElementById('nav-dashboard');
      const navMedia = document.getElementById('nav-media');
      if (mediaMode) {
        dashboardPage.style.display = 'none';
        mediaPage.style.display = 'grid';
        renderMediaPage(summary);
        navDashboard.classList.remove('active');
        navMedia.classList.add('active');
      } else {
        dashboardPage.style.display = 'grid';
        mediaPage.style.display = 'none';
        navMedia.classList.remove('active');
        navDashboard.classList.add('active');
      }
    }
    loadData();
    setInterval(loadData, 15000);
  </script>
</body>
</html>"""
    return template.replace("__BOOTSTRAP_DATA__", bootstrap_json)


class _DashboardHandler(BaseHTTPRequestHandler):
    storage: Storage
    settings: dict[str, Any]

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/api/summary"):
            self._send_json(self._summary_payload())
            return
        if self.path.startswith("/api/recent"):
            self._send_json(self._recent_payload())
            return
        if self.path.startswith("/api/media"):
            topic = parse_qs(urlparse(self.path).query).get("topic", [""])[0]
            self._send_json(_media_payload(topic))
            return
        self._send_html(_render_index())

    def do_HEAD(self) -> None:  # noqa: N802
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
        body = _render_index().encode("utf-8")
        self._send_headers("text/html; charset=utf-8", len(body))

    def _summary_payload(self) -> dict[str, Any]:
        return _summary_payload(self.storage, self.settings)

    def _recent_payload(self) -> dict[str, Any]:
        return _recent_payload(self.storage)

    def _send_json(self, payload: dict[str, Any]) -> None:
        data = json.dumps(payload).encode("utf-8")
        self._send_headers("application/json; charset=utf-8", len(data))
        self.wfile.write(data)

    def _send_headers(self, content_type: str, content_length: int) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(content_length))
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
        "summary": _summary_payload(storage, settings or {}),
        "recent": _recent_payload(storage),
    }
    html = _render_index(snapshot)
    Path(path).write_text(html, encoding="utf-8")
