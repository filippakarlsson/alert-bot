from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, List, Sequence

from .fetchers import FeedItem


STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "but",
    "by",
    "for",
    "from",
    "has",
    "have",
    "he",
    "her",
    "his",
    "how",
    "i",
    "in",
    "is",
    "it",
    "its",
    "just",
    "latest",
    "like",
    "new",
    "of",
    "on",
    "or",
    "our",
    "out",
    "she",
    "so",
    "than",
    "that",
    "the",
    "their",
    "them",
    "there",
    "these",
    "they",
    "this",
    "to",
    "today",
    "was",
    "we",
    "what",
    "when",
    "where",
    "who",
    "why",
    "will",
    "with",
    "you",
    "your",
    "announces",
    "announce",
    "announced",
    "reveals",
    "reveal",
    "revealed",
    "drops",
    "drop",
    "dropped",
    "shares",
    "share",
    "shared",
    "says",
    "say",
    "said",
    "debuts",
    "debut",
    "debuts",
    "teases",
    "tease",
    "teased",
    "review",
    "first",
    "look",
    "trailer",
    "clip",
    "teaser",
    "seen",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
    "january",
    "february",
    "march",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
    "idag",
    "igår",
    "imorgon",
    "tv",
    "report",
    "reports",
    "uppdatering",
    "uppdateringar",
    "nyheterna",
    "nyheter",
    "senaste",
    "live",
    "breaking",
    "today",
    "tonight",
    "watch",
    "update",
    "updates",
    "fpl",
    "scout",
}

GENERIC_LABELS = {
    "nyheter",
    "nyhet",
    "musik",
    "musikfestival",
    "musikfestivaler",
    "festival",
    "festivaler",
    "låt",
    "låtar",
    "album",
    "artist",
    "artister",
    "musikgrupp",
    "filmer",
    "film",
    "tv",
    "tv-program",
    "tv-serie",
    "tv-serier",
    "serie",
    "serier",
    "program",
    "politik",
    "popkultur",
    "nöje",
    "kändis",
    "kändisar",
    "spel",
    "internet",
    "virala trender",
    "youtube",
    "sociala medier",
    "reality-tv",
}

GENERIC_SINGLE_WORDS = {
    "nyhet",
    "nyheter",
    "musik",
    "film",
    "tv",
    "serie",
    "serier",
    "program",
    "politik",
    "kändis",
    "kändisar",
    "spel",
    "internet",
    "youtube",
}

SOURCE_TAIL_RE = re.compile(
    r"\s[-–—]\s(?:Aftonbladet|Expressen|SVT(?: Nyheter)?|TV4(?: Nyheterna)?|Omni|Reuters|AP News|BBC|People\.com|Billboard|Variety|The Verge|Yahoo(?: Sports)?|CNBC|TMZ|E!\s*Online|[A-Za-z0-9.-]+\.(?:se|com|org|net))$",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class TrendSignal:
    label: str
    example_title: str
    source: str
    score: int


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[A-Za-zÅÄÖåäö0-9][A-Za-zÅÄÖåäö0-9'\-]*", text)


def _clean_headline(title: str) -> str:
    cleaned = _strip_source_tail(title.strip())
    if "|" in cleaned:
        cleaned = cleaned.split("|", 1)[0].strip()
    if " - " in cleaned:
        cleaned = cleaned.split(" - ", 1)[0].strip()
    # Remove broadcaster-style generic lead-ins.
    cleaned = re.sub(r"^(just nu|senaste|breaking|live|nu)\s*[:\-–—]?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _strip_source_tail(text: str) -> str:
    value = (text or "").strip()
    if not value:
        return ""
    previous = None
    while previous != value:
        previous = value
        value = SOURCE_TAIL_RE.sub("", value).strip()
    return value


def _normalize_token(token: str) -> str:
    return re.sub(r"^[^A-Za-zÅÄÖåäö0-9]+|[^A-Za-zÅÄÖåäö0-9]+$", "", token).lower()


def _is_signal_token(token: str, blocked_terms: Sequence[str]) -> bool:
    normalized = _normalize_token(token)
    if not normalized:
        return False
    if normalized in STOPWORDS:
        return False
    return not any(term.lower() in normalized for term in blocked_terms)


def _simplify_title(title: str, blocked_terms: Sequence[str]) -> List[str]:
    tokens = _tokenize(_clean_headline(title))
    simplified = []
    for token in tokens:
        normalized = _normalize_token(token)
        if not normalized:
            continue
        if normalized in STOPWORDS:
            continue
        if any(term.lower() in normalized for term in blocked_terms):
            continue
        if len(normalized) <= 1:
            continue
        simplified.append(token.strip("'"))
    return simplified


def _signal_text(item: FeedItem) -> str:
    summary = (item.summary or "").strip()
    if not summary:
        return item.title
    return f"{item.title} {summary}"


def _title_score(tokens: Sequence[str]) -> int:
    score = 0
    for token in tokens:
        if any(ch.isdigit() for ch in token):
            score += 2
        if token[:1].isupper():
            score += 2
        if len(token) >= 8:
            score += 1
    score += len(tokens)
    return score


def _ngrams(tokens: Sequence[str], min_size: int = 2, max_size: int = 5) -> Iterable[str]:
    length = len(tokens)
    for size in range(min_size, min(max_size, length) + 1):
        for start in range(0, length - size + 1):
            yield " ".join(tokens[start : start + size])


def _label_is_generic(label: str) -> bool:
    normalized = re.sub(r"\s+", " ", label.lower().strip())
    return normalized in GENERIC_LABELS


def _label_is_too_broad(label: str) -> bool:
    normalized = re.sub(r"\s+", " ", label.lower().strip())
    if not normalized:
        return True
    if normalized in GENERIC_LABELS:
        return True
    tokens = normalized.split()
    if len(tokens) == 1:
        return True
    if len(tokens) == 2:
        if all(token in GENERIC_SINGLE_WORDS for token in tokens):
            return True
        return False
    generic_hits = sum(1 for token in tokens if token in GENERIC_LABELS)
    return generic_hits >= max(1, len(tokens) // 2)


def _label_has_signal_token(label: str) -> bool:
    tokens = label.split()
    return any(token[:1].isupper() or any(ch.isdigit() for ch in token) for token in tokens)


def _label_is_dateish(label: str) -> bool:
    value = re.sub(r"\s+", " ", label.lower().strip())
    if not value:
        return True
    if re.fullmatch(r"\d{1,2}(\s*[/-]\s*\d{1,2})?(\s*[/-]\s*\d{2,4})?", value):
        return True
    month_words = {
        "jan", "january", "feb", "february", "mar", "march", "apr", "april", "may",
        "jun", "june", "jul", "july", "aug", "august", "sep", "sept", "september",
        "oct", "october", "nov", "november", "dec", "december",
    }
    parts = value.split()
    if len(parts) <= 3 and any(part in month_words for part in parts):
        return True
    return False


def _is_clear_label(label: str) -> bool:
    normalized = re.sub(r"\s+", " ", label).strip()
    if not normalized:
        return False
    if _label_is_too_broad(normalized):
        return False
    if _label_is_dateish(normalized):
        return False
    if len(normalized.split()) < 2:
        return False
    return True


def _headline_to_label(headline: str, fallback: str) -> str:
    clean = _strip_source_tail(_clean_headline(headline))
    if ":" in clean:
        left, right = clean.split(":", 1)
        right = right.strip()
        if right and len(_simplify_title(right, ())) >= 2:
            clean = right
    tokens = _simplify_title(clean, ())
    if len(tokens) >= 3:
        return " ".join(tokens[:7])
    if len(tokens) >= 2:
        return " ".join(tokens[:8])
    fallback_clean = _strip_source_tail(_clean_headline(fallback or ""))
    if fallback_clean and len(_simplify_title(fallback_clean, ())) >= 2:
        return fallback_clean
    return clean or fallback_clean or fallback


def _canonical_story_key(item: FeedItem, blocked_terms: Sequence[str]) -> str:
    tokens = [_normalize_token(tok) for tok in _simplify_title(_signal_text(item), blocked_terms)]
    tokens = [tok for tok in tokens if tok and tok not in STOPWORDS]
    if not tokens:
        return _normalize_token(_clean_headline(item.title)) or item.id
    return " ".join(tokens[:12])


def dedupe_feed_items(items: Sequence[FeedItem], blocked_terms: Sequence[str]) -> List[FeedItem]:
    unique: List[FeedItem] = []
    seen: set[str] = set()
    for item in items:
        key = _canonical_story_key(item, blocked_terms)
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _extract_entities(text: str, blocked_terms: Sequence[str]) -> List[str]:
    candidates = re.findall(r"(?:[#@]?[A-ZÅÄÖ][A-Za-zÅÄÖåäö0-9'’.-]*(?:\s+[A-ZÅÄÖ0-9][A-Za-zÅÄÖåäö0-9'’.-]*){0,4})", text)
    entities: List[str] = []
    for cand in candidates:
        clean = re.sub(r"\s+", " ", cand).strip(" -–—,.;:!?")
        if not clean:
            continue
        words = [_normalize_token(part) for part in clean.split()]
        words = [w for w in words if w]
        if not words:
            continue
        if len(words) == 1 and (words[0] in STOPWORDS or len(words[0]) < 3):
            continue
        if any(any(bt.lower() in w for bt in blocked_terms) for w in words):
            continue
        norm = " ".join(words)
        if norm in {"svenska", "sverige", "tv", "nyhet", "nyheter", "musik", "film", "filmer"}:
            continue
        entities.append(clean)
    return entities


def normalize_cluster_key(text: str) -> str:
    tokens = []
    for token in _simplify_title(text, ()):
        normalized = _normalize_token(token)
        if not normalized or normalized in STOPWORDS:
            continue
        tokens.append(normalized)
    if not tokens:
        return "cluster:default"
    return "cluster:" + " ".join(tokens[:6])


def extract_trend_signal(items: Sequence[FeedItem], blocked_terms: Sequence[str], source: str) -> TrendSignal | None:
    if not items:
        return None

    items = dedupe_feed_items(items, blocked_terms)
    if not items:
        return None

    item_tokens: List[tuple[FeedItem, List[str]]] = [
        (item, _simplify_title(_signal_text(item), blocked_terms))
        for item in items
    ]
    item_tokens = [(item, tokens) for item, tokens in item_tokens if tokens]
    simplified_titles: List[List[str]] = [tokens for _, tokens in item_tokens]
    if not simplified_titles:
        return None

    entity_counts: Counter[str] = Counter()
    entity_example: dict[str, FeedItem] = {}
    for item in items:
        seen_entities = set(_extract_entities(_signal_text(item), blocked_terms))
        for ent in seen_entities:
            entity_counts[ent] += 1
            entity_example.setdefault(ent, item)

    strong_entities = [(ent, cnt) for ent, cnt in entity_counts.items() if cnt >= 2]
    if strong_entities:
        ent, cnt = max(strong_entities, key=lambda entry: (entry[1], len(entry[0])))
        ex_item = entity_example[ent]
        label = _headline_to_label(ex_item.title, ent)
        if _label_is_too_broad(label):
            label = ent
        return TrendSignal(
            label=label,
            example_title=ex_item.title,
            source=source,
            score=cnt + 2,
        )

    ngram_counts: Counter[str] = Counter()
    ngram_examples: dict[str, str] = {}
    for item, tokens in item_tokens:
        unique_ngrams = set(_ngrams(tokens))
        for phrase in unique_ngrams:
            ngram_counts[phrase] += 1
            ngram_examples.setdefault(phrase, item.title)

    repeated = [
        (phrase, count)
        for phrase, count in ngram_counts.items()
        if count >= 2 and not _label_is_generic(phrase) and _label_has_signal_token(phrase)
    ]
    if repeated:
        phrase, count = max(
            repeated,
            key=lambda entry: (entry[1], len(entry[0].split()), len(entry[0])),
        )
        phrase_title = phrase.title()
        if not _is_clear_label(phrase_title):
            phrase_title = _headline_to_label(ngram_examples[phrase], phrase_title)
        return TrendSignal(
            label=phrase_title,
            example_title=ngram_examples[phrase],
            source=source,
            score=count,
        )

    best_tokens = max(simplified_titles, key=_title_score)
    label_tokens = best_tokens[:6]
    label = " ".join(label_tokens)
    example_title = next(
        (item.title for item, tokens in item_tokens if tokens == best_tokens),
        items[0].title,
    )
    if not _is_clear_label(label):
        label = _headline_to_label(example_title, label or items[0].title)
    return TrendSignal(
        label=label,
        example_title=example_title,
        source=source,
        score=_title_score(best_tokens),
    )


def choose_alert_topic(signal: TrendSignal | None, fallback_topic: str) -> tuple[str, str]:
    if signal is None:
        return fallback_topic.strip(), ""
    headline = _clean_headline(signal.example_title)
    label = (signal.label or "").strip()

    if not label:
        label = headline or fallback_topic
    if _label_is_too_broad(label) or _label_is_dateish(label):
        label = headline or label or fallback_topic
    if _label_is_too_broad(label) or _label_is_dateish(label):
        label = fallback_topic

    normalized = re.sub(r"\s+", " ", label).strip()
    if len(normalized) > 120:
        normalized = normalized[:117].rstrip() + "..."
    return normalized, headline
