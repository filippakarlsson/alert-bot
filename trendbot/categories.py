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
    if any(
        term in lowered
        for term in {
            "politik",
            "politiskt",
            "val",
            "regering",
            "riksdag",
            "president",
            "statsminister",
            "minister",
            "trump",
            "biden",
            "putin",
            "zelensky",
            "netanyahu",
            "erdogan",
        }
    ):
        return "politics"
    if any(term in lowered for term in {"popkultur", "nöje", "kändis", "kändisar", "film", "tv", "serie", "festival", "galan"}):
        return "pop_culture"
    if any(term in lowered for term in {"musik", "k-pop", "eurovision", "melodifestivalen", "album", "låt", "artist", "turné"}):
        return "music"
    if any(term in lowered for term in {"nyhet", "nyheter", "senaste", "världen", "uppdatering", "rubrik"}):
        return "news"
    if any(term in lowered for term in {"tiktok", "youtube", "influencer", "streamer", "streamers", "meme", "memes", "viral", "internet", "skaparekonomi"}):
        return "internet"
    if any(term in lowered for term in {"spel", "gaming", "esport", "streaming", "podd", "poddar"}):
        return "gaming"
    return "default"


def category_color(category: str) -> int:
    return CATEGORY_COLORS.get(category, CATEGORY_COLORS["default"])
