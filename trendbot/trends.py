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
}

GENERIC_LABELS = {
    "news",
    "music",
    "music group",
    "movies",
    "movie",
    "tv",
    "television",
    "politics",
    "pop culture",
    "celebrity",
}


@dataclass(frozen=True)
class TrendSignal:
    label: str
    example_title: str
    source: str
    score: int


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[A-Za-z0-9][A-Za-z0-9'\-]*", text)


def _clean_headline(title: str) -> str:
    cleaned = title.strip()
    if "|" in cleaned:
        cleaned = cleaned.split("|", 1)[1].strip()
    if " - " in cleaned:
        cleaned = cleaned.split(" - ", 1)[0].strip()
    return cleaned


def _normalize_token(token: str) -> str:
    return re.sub(r"^[^A-Za-z0-9]+|[^A-Za-z0-9]+$", "", token).lower()


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
        simplified.append(token.strip("'"))
    return simplified


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


def _label_has_signal_token(label: str) -> bool:
    tokens = label.split()
    return any(token[:1].isupper() or any(ch.isdigit() for ch in token) for token in tokens)


def extract_trend_signal(items: Sequence[FeedItem], blocked_terms: Sequence[str], source: str) -> TrendSignal | None:
    if not items:
        return None

    item_tokens: List[tuple[FeedItem, List[str]]] = [
        (item, _simplify_title(item.title, blocked_terms))
        for item in items
    ]
    item_tokens = [(item, tokens) for item, tokens in item_tokens if tokens]
    simplified_titles: List[List[str]] = [tokens for _, tokens in item_tokens]
    if not simplified_titles:
        return None

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
        return TrendSignal(
            label=phrase.title(),
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
    return TrendSignal(
        label=label,
        example_title=example_title,
        source=source,
        score=_title_score(best_tokens),
    )
