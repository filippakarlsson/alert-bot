from __future__ import annotations

CATEGORY_COLORS = {
    "pop_culture": 0xF59E0B,
    "music": 0xEC4899,
    "politics": 0x3B82F6,
    "news": 0x06B6D4,
    "internet": 0x22C55E,
    "gaming": 0x8B5CF6,
    "default": 0xF97316,
}


def categorize_topic(topic: str) -> str:
    lowered = topic.lower()
    if any(term in lowered for term in {"pop culture", "celebrity", "movie", "movies", "tv", "film", "festival", "award"}):
        return "pop_culture"
    if any(term in lowered for term in {"music", "k-pop", "eurovision", "album", "song", "artist", "tour"}):
        return "music"
    if any(term in lowered for term in {"politics", "election", "government", "congress", "president", "political"}):
        return "politics"
    if any(term in lowered for term in {"news", "breaking", "world", "update", "headline"}):
        return "news"
    if any(term in lowered for term in {"tiktok", "youtube", "influencer", "streamer", "streamers", "memes", "viral", "internet", "creator", "creator economy"}):
        return "internet"
    if any(term in lowered for term in {"gaming", "game", "esports", "streaming", "podcast", "podcasts"}):
        return "gaming"
    return "default"


def category_color(category: str) -> int:
    return CATEGORY_COLORS.get(category, CATEGORY_COLORS["default"])
