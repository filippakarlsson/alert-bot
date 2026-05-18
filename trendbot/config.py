from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass
from typing import List


def _csv_env(name: str, default: str = "") -> List[str]:
    raw = os.getenv(name, default)
    return [part.strip() for part in raw.split(",") if part.strip()]


def _bool_env(name: str, default: str = "false") -> bool:
    raw = os.getenv(name, default).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _load_dotenv(path: str = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            # Never override platform-provided env vars (Render, etc.).
            os.environ[key] = value


@dataclass(frozen=True)
class Config:
    discord_webhook_url: str
    discord_posts_webhook_url: str
    topics: List[str]
    blocked_terms: List[str]
    reddit_enabled: bool
    reddit_topic_limit: int
    reddit_subreddits: List[str]
    alert_min_sources: int
    alert_ratio_threshold: float
    alert_cooldown_seconds: int
    alert_global_cooldown_seconds: int
    daily_digest_interval_seconds: int
    dashboard_enabled: bool
    dashboard_host: str
    dashboard_port: int
    dashboard_snapshot_path: str
    debug_mode: bool
    poll_interval_seconds: int
    daily_series_bucket_seconds: int
    daily_series_window_seconds: int
    heartbeat_interval_seconds: int
    alert_count_offset: int
    window_size: int
    spike_multiplier: float
    min_baseline: int
    pop_culture_spike_multiplier: float
    pop_culture_min_baseline: int
    reddit_limit: int
    reddit_timeout_seconds: int
    reddit_refresh_seconds: int
    reddit_request_delay_seconds: float
    reddit_backoff_seconds: int
    rss_refresh_seconds: int
    google_news_hl: str
    google_news_gl: str
    google_news_ceid: str
    google_news_recency_query: str
    swedish_only_mode: bool
    max_item_age_hours: int
    require_item_timestamp: bool
    skip_previous_year_titles: bool
    enable_source_google_se: bool
    enable_source_google_global: bool
    enable_source_bbc: bool
    enable_source_npr: bool
    enable_source_ap: bool
    enable_source_variety: bool
    enable_source_billboard: bool
    enable_source_the_verge: bool
    enable_source_people: bool
    enable_source_eonline: bool
    enable_source_tmz: bool
    enable_source_rollingstone: bool
    enable_source_aftonbladet: bool
    enable_source_expressen: bool
    enable_source_hant: bool
    enable_source_hant_extra: bool
    enable_source_svenskdam: bool
    enable_source_nyheter24_noje: bool
    enable_source_svt: bool
    enable_source_tv4: bool
    enable_source_tiktok: bool
    db_path: str


def load_config() -> Config:
    _load_dotenv()
    swedish_only_mode = _bool_env("SWEDISH_ONLY_MODE", "true")
    topics_raw = os.getenv("TRENDBOT_TOPICS_ACTIVE", "").strip()
    topics = _csv_env(
        "TRENDBOT_TOPICS_ACTIVE" if topics_raw else "TRENDBOT_TOPICS",
        "pop culture,music,politics,news,movies,tv,celebrity,K-pop,Eurovision,TikTok,influencer,streamers,youtube,memes,viral trends,internet culture,creator economy,viral video,gaming,podcasts,streaming,fashion,sports",
    )
    return Config(
        discord_webhook_url=os.getenv("DISCORD_WEBHOOK_URL", "").strip(),
        discord_posts_webhook_url=os.getenv("DISCORD_POSTS_WEBHOOK_URL", "").strip(),
        topics=topics,
        blocked_terms=_csv_env(
            "TRENDBOT_BLOCKED_TERMS",
            (
                "ai,openai,chatgpt,artificial intelligence,machine learning,"
                "nhl,nfl,nba,mlb,ncaa,super bowl,stanley cup,march madness"
            ),
        ),
        reddit_enabled=_bool_env("REDDIT_ENABLED", "false"),
        reddit_topic_limit=int(os.getenv("REDDIT_TOPIC_LIMIT", "5")),
        reddit_subreddits=_csv_env(
            "TRENDBOT_REDDIT_SUBREDDITS",
            "popculturechat,popculture,entertainment,movies,tv,television,music,kpop,eurovision,tiktok,celebrity,streaming,streamers,youtube",
        ),
        alert_min_sources=int(os.getenv("ALERT_MIN_SOURCES", "2")),
        alert_ratio_threshold=float(os.getenv("ALERT_RATIO_THRESHOLD", "2.5")),
        alert_cooldown_seconds=int(os.getenv("ALERT_COOLDOWN_SECONDS", "3600")),
        alert_global_cooldown_seconds=int(os.getenv("ALERT_GLOBAL_COOLDOWN_SECONDS", "0")),
        daily_digest_interval_seconds=int(os.getenv("DAILY_DIGEST_INTERVAL_SECONDS", "86400")),
        dashboard_enabled=_bool_env("DASHBOARD_ENABLED", "false"),
        dashboard_host=os.getenv("DASHBOARD_HOST", "0.0.0.0").strip(),
        dashboard_port=int(os.getenv("DASHBOARD_PORT", "8000")),
        dashboard_snapshot_path=os.getenv("DASHBOARD_SNAPSHOT_PATH", "trendbot-dashboard.html").strip(),
        debug_mode=_bool_env("DEBUG_MODE", "false"),
        poll_interval_seconds=int(os.getenv("POLL_INTERVAL_SECONDS", "300")),
        daily_series_bucket_seconds=int(os.getenv("DAILY_SERIES_BUCKET_SECONDS", "180")),
        daily_series_window_seconds=int(os.getenv("DAILY_SERIES_WINDOW_SECONDS", "21600")),
        heartbeat_interval_seconds=int(os.getenv("HEARTBEAT_INTERVAL_SECONDS", "3600")),
        alert_count_offset=int(os.getenv("ALERT_COUNT_OFFSET", "0")),
        window_size=int(os.getenv("WINDOW_SIZE", "12")),
        spike_multiplier=float(os.getenv("SPIKE_MULTIPLIER", "2.5")),
        min_baseline=int(os.getenv("MIN_BASELINE", "2")),
        pop_culture_spike_multiplier=float(os.getenv("POP_CULTURE_SPIKE_MULTIPLIER", "2.0")),
        pop_culture_min_baseline=int(os.getenv("POP_CULTURE_MIN_BASELINE", "1")),
        reddit_limit=int(os.getenv("REDDIT_LIMIT", "25")),
        reddit_timeout_seconds=int(os.getenv("REDDIT_TIMEOUT_SECONDS", "15")),
        reddit_refresh_seconds=int(os.getenv("REDDIT_REFRESH_SECONDS", "900")),
        reddit_request_delay_seconds=float(os.getenv("REDDIT_REQUEST_DELAY_SECONDS", "1.2")),
        reddit_backoff_seconds=int(os.getenv("REDDIT_BACKOFF_SECONDS", "1800")),
        rss_refresh_seconds=int(os.getenv("RSS_REFRESH_SECONDS", "300")),
        google_news_hl=os.getenv("GOOGLE_NEWS_HL", "en-US").strip(),
        google_news_gl=os.getenv("GOOGLE_NEWS_GL", "US").strip(),
        google_news_ceid=os.getenv("GOOGLE_NEWS_CEID", "US:en").strip(),
        google_news_recency_query=os.getenv("GOOGLE_NEWS_RECENCY_QUERY", "when:2d").strip(),
        swedish_only_mode=swedish_only_mode,
        max_item_age_hours=int(os.getenv("MAX_ITEM_AGE_HOURS", "72")),
        require_item_timestamp=_bool_env("REQUIRE_ITEM_TIMESTAMP", "true"),
        skip_previous_year_titles=_bool_env("SKIP_PREVIOUS_YEAR_TITLES", "true"),
        enable_source_google_se=_bool_env("ENABLE_SOURCE_GOOGLE_SE", "true"),
        enable_source_google_global=_bool_env("ENABLE_SOURCE_GOOGLE_GLOBAL", "false" if swedish_only_mode else "true"),
        enable_source_bbc=_bool_env("ENABLE_SOURCE_BBC", "false" if swedish_only_mode else "true"),
        enable_source_npr=_bool_env("ENABLE_SOURCE_NPR", "false" if swedish_only_mode else "true"),
        enable_source_ap=_bool_env("ENABLE_SOURCE_AP", "false" if swedish_only_mode else "true"),
        enable_source_variety=_bool_env("ENABLE_SOURCE_VARIETY", "false" if swedish_only_mode else "true"),
        enable_source_billboard=_bool_env("ENABLE_SOURCE_BILLBOARD", "false" if swedish_only_mode else "true"),
        enable_source_the_verge=_bool_env("ENABLE_SOURCE_THE_VERGE", "false" if swedish_only_mode else "true"),
        enable_source_people=_bool_env("ENABLE_SOURCE_PEOPLE", "false" if swedish_only_mode else "true"),
        enable_source_eonline=_bool_env("ENABLE_SOURCE_EONLINE", "false" if swedish_only_mode else "true"),
        enable_source_tmz=_bool_env("ENABLE_SOURCE_TMZ", "false" if swedish_only_mode else "true"),
        enable_source_rollingstone=_bool_env("ENABLE_SOURCE_ROLLINGSTONE", "false" if swedish_only_mode else "true"),
        enable_source_aftonbladet=_bool_env("ENABLE_SOURCE_AFTONBLADET", "true"),
        enable_source_expressen=_bool_env("ENABLE_SOURCE_EXPRESSEN", "true"),
        enable_source_hant=_bool_env("ENABLE_SOURCE_HANT", "true"),
        enable_source_hant_extra=_bool_env("ENABLE_SOURCE_HANT_EXTRA", "false"),
        enable_source_svenskdam=_bool_env("ENABLE_SOURCE_SVENSKDAM", "true"),
        enable_source_nyheter24_noje=_bool_env("ENABLE_SOURCE_NYHETER24_NOJE", "true"),
        enable_source_svt=_bool_env("ENABLE_SOURCE_SVT", "true"),
        enable_source_tv4=_bool_env("ENABLE_SOURCE_TV4", "true"),
        enable_source_tiktok=_bool_env("ENABLE_SOURCE_TIKTOK", "false"),
        db_path=os.getenv("TRENDBOT_DB_PATH", "trendbot.sqlite3"),
    )
