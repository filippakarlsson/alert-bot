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
            os.environ[key] = value


@dataclass(frozen=True)
class Config:
    discord_webhook_url: str
    topics: List[str]
    blocked_terms: List[str]
    reddit_enabled: bool
    reddit_topic_limit: int
    reddit_subreddits: List[str]
    debug_mode: bool
    poll_interval_seconds: int
    heartbeat_interval_seconds: int
    window_size: int
    spike_multiplier: float
    min_baseline: int
    pop_culture_spike_multiplier: float
    pop_culture_min_baseline: int
    reddit_limit: int
    reddit_timeout_seconds: int
    google_news_hl: str
    google_news_gl: str
    google_news_ceid: str
    db_path: str


def load_config() -> Config:
    _load_dotenv()
    topics = _csv_env(
        "TRENDBOT_TOPICS",
        "pop culture,music,politics,news,movies,tv,celebrity,K-pop,Eurovision,TikTok,influencer,streamers,youtube,memes,viral trends,internet culture,creator economy,viral video,gaming,podcasts,streaming,fashion,sports",
    )
    return Config(
        discord_webhook_url=os.getenv("DISCORD_WEBHOOK_URL", "").strip(),
        topics=topics,
        blocked_terms=_csv_env(
            "TRENDBOT_BLOCKED_TERMS",
            "ai,openai,chatgpt,artificial intelligence,machine learning",
        ),
        reddit_enabled=_bool_env("REDDIT_ENABLED", "false"),
        reddit_topic_limit=int(os.getenv("REDDIT_TOPIC_LIMIT", "5")),
        reddit_subreddits=_csv_env(
            "TRENDBOT_REDDIT_SUBREDDITS",
            "popculturechat,popculture,entertainment,movies,tv,television,music,kpop,eurovision,tiktok,celebrity,streaming,streamers,youtube",
        ),
        debug_mode=_bool_env("DEBUG_MODE", "false"),
        poll_interval_seconds=int(os.getenv("POLL_INTERVAL_SECONDS", "300")),
        heartbeat_interval_seconds=int(os.getenv("HEARTBEAT_INTERVAL_SECONDS", "3600")),
        window_size=int(os.getenv("WINDOW_SIZE", "12")),
        spike_multiplier=float(os.getenv("SPIKE_MULTIPLIER", "2.5")),
        min_baseline=int(os.getenv("MIN_BASELINE", "2")),
        pop_culture_spike_multiplier=float(os.getenv("POP_CULTURE_SPIKE_MULTIPLIER", "2.0")),
        pop_culture_min_baseline=int(os.getenv("POP_CULTURE_MIN_BASELINE", "1")),
        reddit_limit=int(os.getenv("REDDIT_LIMIT", "25")),
        reddit_timeout_seconds=int(os.getenv("REDDIT_TIMEOUT_SECONDS", "15")),
        google_news_hl=os.getenv("GOOGLE_NEWS_HL", "en-US").strip(),
        google_news_gl=os.getenv("GOOGLE_NEWS_GL", "US").strip(),
        google_news_ceid=os.getenv("GOOGLE_NEWS_CEID", "US:en").strip(),
        db_path=os.getenv("TRENDBOT_DB_PATH", "trendbot.sqlite3"),
    )
