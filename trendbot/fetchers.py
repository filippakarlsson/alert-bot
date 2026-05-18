from __future__ import annotations

import html
import urllib.error
from email.utils import parsedate_to_datetime
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional


@dataclass(frozen=True)
class FeedItem:
    id: str
    title: str
    url: str
    created_utc: int
    summary: str = ""


_TOPIC_SOFT_TERMS = {
    "svensk",
    "svenska",
    "sverige",
    "sweden",
    "global",
    "america",
    "english",
    "nöje",
    "noje",
    "popkultur",
    "popculture",
    "pop",
    "culture",
    "news",
    "nyheter",
    "music",
    "musik",
    "tv",
    "film",
    "movie",
    "movies",
    "politics",
    "gaming",
    "internet",
    "viral",
    "trends",
    "celebrity",
    "influencer",
    "streamers",
    "youtube",
    "podcasts",
    "streaming",
    "fashion",
    "sports",
}


def _topic_terms(topic: str) -> List[str]:
    return [part for part in re.split(r"\s+", topic.lower().strip()) if part]


def _topic_match_terms(topic: str | List[str]) -> tuple[List[str], bool]:
    terms = topic if isinstance(topic, list) else _topic_terms(topic)
    base_terms = [term for term in terms if len(term) >= 3]
    if not base_terms:
        return ([], False)
    significant = [term for term in base_terms if term not in _TOPIC_SOFT_TERMS]
    if significant:
        return (significant, False)
    # If all tokens are soft/generic, use loose matching (not strict-all) so feeds still produce signals.
    return (base_terms, False)


def _matches_topic_terms(terms: List[str], haystack: str, strict_all: bool = False) -> bool:
    if not terms:
        return True
    if strict_all:
        return all(term in haystack for term in terms)
    matches = sum(1 for term in terms if term in haystack)
    # Quarter-threshold keeps matching resilient when topic terms are generic/multi-word.
    if len(terms) <= 3:
        required = 1
    elif len(terms) <= 8:
        required = 2
    else:
        required = 3
    return matches >= required


class RedditFetcher:
    source_name = "reddit"
    _ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}

    def __init__(
        self,
        limit: int = 25,
        timeout_seconds: int = 15,
        subreddits: Optional[List[str]] = None,
        refresh_seconds: int = 900,
        request_delay_seconds: float = 1.2,
        backoff_seconds: int = 1800,
    ) -> None:
        self.limit = limit
        self.timeout_seconds = timeout_seconds
        self.subreddits = [sub.strip().lstrip("r/").lower() for sub in (subreddits or []) if sub.strip()]
        self.refresh_seconds = max(60, int(refresh_seconds))
        self.request_delay_seconds = max(0.0, float(request_delay_seconds))
        self.backoff_seconds = max(300, int(backoff_seconds))
        self._cached_items: List[FeedItem] | None = None
        self._cached_at_utc: int = 0
        self._backoff_until_utc: int = 0

    def search(self, topic: str) -> List[FeedItem]:
        topic_terms = self._topic_terms(topic)
        posts: List[FeedItem] = []
        source_items = self._fetch_items(topic)
        for item in source_items:
            if not self._matches_topic(topic_terms, item.title, f"{item.summary} {item.url}"):
                continue
            posts.append(item)
            if len(posts) >= self.limit:
                break
        return posts

    def _fetch_items(self, topic: str) -> List[FeedItem]:
        if self.subreddits:
            now = int(time.time())
            if now < self._backoff_until_utc:
                return self._cached_items or []
            cache_age = now - self._cached_at_utc if self._cached_at_utc else None
            if self._cached_items is not None and cache_age is not None and cache_age < self.refresh_seconds:
                return self._cached_items
            refreshed = self._fetch_whitelisted_subreddits()
            if refreshed:
                self._cached_items = refreshed
                self._cached_at_utc = now
            elif self._cached_items is None:
                self._cached_items = []
                self._cached_at_utc = now
            return self._cached_items
        return self._fetch_search_results(topic)

    def _fetch_search_results(self, topic: str) -> List[FeedItem]:
        query = urllib.parse.urlencode(
            {
                "q": topic,
                "sort": "new",
                "t": "day",
                "limit": str(self.limit),
            }
        )
        return self._fetch_feed(f"https://www.reddit.com/search.rss?{query}")

    def _fetch_whitelisted_subreddits(self) -> List[FeedItem]:
        items: List[FeedItem] = []
        seen_ids: set[str] = set()
        for index, subreddit in enumerate(self.subreddits):
            feed_url = f"https://www.reddit.com/r/{subreddit}/new/.rss?limit={self.limit}"
            feed_items = self._fetch_feed(feed_url)
            for item in feed_items:
                if item.id in seen_ids:
                    continue
                items.append(item)
                seen_ids.add(item.id)
            if self.request_delay_seconds > 0 and index < len(self.subreddits) - 1:
                time.sleep(self.request_delay_seconds)
        return items

    def _fetch_feed(self, url: str) -> List[FeedItem]:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 trendbot/0.1",
                "Accept": "application/atom+xml,application/xml,text/xml;q=0.9,*/*;q=0.8",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = response.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                self._backoff_until_utc = int(time.time()) + self.backoff_seconds
                return []
            if exc.code == 404:
                return []
            raise
        return self._parse_feed(payload)

    def _parse_feed(self, payload: bytes) -> List[FeedItem]:
        posts: List[FeedItem] = []
        root = ET.fromstring(payload)
        for entry in root.findall("atom:entry", self._ATOM_NS):
            entry_id = entry.findtext("atom:id", default="", namespaces=self._ATOM_NS).strip()
            if not entry_id or not entry_id.startswith("t3_"):
                continue
            title = html.unescape(
                entry.findtext("atom:title", default="", namespaces=self._ATOM_NS).strip()
            )
            link_el = entry.find("atom:link", self._ATOM_NS)
            link = link_el.attrib.get("href", "") if link_el is not None else ""
            summary = html.unescape(
                entry.findtext("atom:summary", default="", namespaces=self._ATOM_NS).strip()
            )
            updated = entry.findtext("atom:updated", default="", namespaces=self._ATOM_NS)
            created_utc = 0
            if updated:
                created_utc = int(
                    datetime.fromisoformat(updated.replace("Z", "+00:00"))
                    .astimezone(timezone.utc)
                    .timestamp()
                )
            posts.append(
                FeedItem(
                    id=entry_id,
                    title=title,
                    url=link,
                    created_utc=created_utc,
                    summary=summary,
                )
            )
        return posts

    @staticmethod
    def _topic_terms(topic: str) -> List[str]:
        return _topic_terms(topic)

    @staticmethod
    def _strip_html(value: str) -> str:
        return html.unescape(re.sub(r"<[^>]+>", " ", value))

    def _matches_topic(self, topic_terms: List[str], title: str, content: str) -> bool:
        haystack = f"{title} {self._strip_html(content)}".lower()
        terms, strict_all = _topic_match_terms(topic_terms)
        return _matches_topic_terms(terms, haystack, strict_all=strict_all)


class GoogleNewsFetcher:
    source_name = "google_news"
    _RSS_NS: dict = {}

    def __init__(
        self,
        limit: int = 25,
        timeout_seconds: int = 15,
        hl: str = "en-US",
        gl: str = "US",
        ceid: str = "US:en",
        query_suffix: str = "",
        refresh_seconds: int = 300,
        stale_fallback_seconds: int = 3600,
    ) -> None:
        self.limit = limit
        self.timeout_seconds = timeout_seconds
        self.hl = hl
        self.gl = gl
        self.ceid = ceid
        self.query_suffix = (query_suffix or "").strip()
        self.refresh_seconds = max(30, int(refresh_seconds))
        self.stale_fallback_seconds = max(self.refresh_seconds, int(stale_fallback_seconds))
        self._cache_by_topic: dict[str, tuple[int, List[FeedItem]]] = {}

    def search(self, topic: str) -> List[FeedItem]:
        now = int(time.time())
        cache_key = topic.strip().lower()
        cached_entry = self._cache_by_topic.get(cache_key)
        if cached_entry:
            cached_at, cached_items = cached_entry
            if now - cached_at < self.refresh_seconds:
                return cached_items

        query_text = topic
        if self.query_suffix:
            query_text = f"{topic} {self.query_suffix}"
        query = urllib.parse.urlencode(
            {
                "q": query_text,
                "hl": self.hl,
                "gl": self.gl,
                "ceid": self.ceid,
            }
        )
        url = f"https://news.google.com/rss/search?{query}"
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 trendbot/0.1",
                "Accept": "application/xml,text/xml;q=0.9,*/*;q=0.8",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = response.read()
        except Exception:
            if cached_entry:
                cached_at, cached_items = cached_entry
                if now - cached_at < self.stale_fallback_seconds:
                    return cached_items
            raise

        items: List[FeedItem] = []
        root = ET.fromstring(payload)
        channel = root.find("channel")
        if channel is None:
            self._cache_by_topic[cache_key] = (now, items)
            return items

        for item in channel.findall("item")[: self.limit]:
            title = self._text(item, "title")
            link = self._text(item, "link")
            guid = self._text(item, "guid") or link
            description = self._text(item, "description")
            pub_date = self._text(item, "pubDate")
            created_utc = self._parse_pub_date(pub_date)
            if not title or not guid:
                continue
            if not self._matches_topic(topic, title, description):
                continue
            items.append(
                FeedItem(
                    id=guid,
                    title=title,
                    url=link,
                    created_utc=created_utc,
                    summary=description,
                )
            )
        self._cache_by_topic[cache_key] = (now, items)
        return items

    @staticmethod
    def _text(item: ET.Element, tag: str) -> str:
        value = item.findtext(tag, default="")
        return html.unescape(value.strip())

    @staticmethod
    def _parse_pub_date(pub_date: str) -> int:
        if not pub_date:
            return 0
        try:
            return int(parsedate_to_datetime(pub_date).astimezone(timezone.utc).timestamp())
        except (TypeError, ValueError, IndexError, OverflowError):
            return 0

    @staticmethod
    def _topic_terms(topic: str) -> List[str]:
        return _topic_terms(topic)

    def _matches_topic(self, topic: str, title: str, description: str) -> bool:
        topic_terms, strict_all = _topic_match_terms(topic)
        haystack = f"{title} {self._strip_html(description)}".lower()
        return _matches_topic_terms(topic_terms, haystack, strict_all=strict_all)

    @staticmethod
    def _strip_html(value: str) -> str:
        return html.unescape(re.sub(r"<[^>]+>", " ", value))


class RSSFetcher:
    def __init__(
        self,
        source_name: str,
        feed_url: str,
        limit: int = 20,
        timeout_seconds: int = 15,
        refresh_seconds: int = 300,
    ) -> None:
        self.source_name = source_name
        self.feed_url = feed_url
        self.limit = limit
        self.timeout_seconds = timeout_seconds
        self.refresh_seconds = max(30, int(refresh_seconds))
        self._cached_items: List[FeedItem] | None = None
        self._cached_at_utc: int = 0

    def search(self, topic: str) -> List[FeedItem]:
        now = int(time.time())
        cache_age = now - self._cached_at_utc if self._cached_at_utc else None
        if self._cached_items is None or cache_age is None or cache_age >= self.refresh_seconds:
            request = urllib.request.Request(
                self.feed_url,
                headers={
                    "User-Agent": "Mozilla/5.0 trendbot/0.1",
                    "Accept": "application/xml,application/rss+xml,application/atom+xml,text/xml;q=0.9,*/*;q=0.8",
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    payload = response.read()
            except urllib.error.HTTPError as exc:
                if self._cached_items:
                    # Keep serving stale cache during transient upstream failures.
                    self._cached_at_utc = now
                    return self._filter_items(self._cached_items, topic)
                if exc.code in {404, 429}:
                    self._cached_items = []
                    self._cached_at_utc = now
                    return []
                raise
            except urllib.error.URLError:
                if self._cached_items:
                    self._cached_at_utc = now
                    return self._filter_items(self._cached_items, topic)
                raise
            parsed_items = self._parse_feed(payload)
            if parsed_items or self._cached_items is None:
                self._cached_items = parsed_items
            self._cached_at_utc = now
        return self._filter_items(self._cached_items or [], topic)

    def _parse_feed(self, payload: bytes) -> List[FeedItem]:
        try:
            root = ET.fromstring(payload)
        except ET.ParseError:
            return []

        posts: List[FeedItem] = []
        channel = root.find("channel")
        if channel is not None:
            for item in channel.findall("item")[: self.limit]:
                title = self._text(item, "title")
                link = self._text(item, "link")
                guid = self._text(item, "guid") or link
                description = self._text(item, "description")
                pub_date = self._text(item, "pubDate")
                created_utc = self._parse_pub_date(pub_date)
                if not title or not guid:
                    continue
                posts.append(
                    FeedItem(
                        id=guid,
                        title=title,
                        url=link,
                        created_utc=created_utc,
                        summary=description,
                    )
                )
            return posts

        atom_ns = {"atom": "http://www.w3.org/2005/Atom"}
        for entry in root.findall("atom:entry", atom_ns):
            entry_id = entry.findtext("atom:id", default="", namespaces=atom_ns).strip()
            if not entry_id:
                continue
            title = html.unescape(entry.findtext("atom:title", default="", namespaces=atom_ns).strip())
            link_el = entry.find("atom:link", atom_ns)
            link = link_el.attrib.get("href", "") if link_el is not None else ""
            summary = entry.findtext("atom:summary", default="", namespaces=atom_ns)
            updated = entry.findtext("atom:updated", default="", namespaces=atom_ns)
            created_utc = 0
            if updated:
                try:
                    created_utc = int(
                        datetime.fromisoformat(updated.replace("Z", "+00:00"))
                        .astimezone(timezone.utc)
                        .timestamp()
                    )
                except ValueError:
                    created_utc = 0
            if not title:
                continue
            posts.append(
                FeedItem(
                    id=entry_id,
                    title=title,
                    url=link,
                    created_utc=created_utc,
                    summary=html.unescape((summary or "").strip()),
                )
            )
            if len(posts) >= self.limit:
                break
        return posts

    def _filter_items(self, items: List[FeedItem], topic: str) -> List[FeedItem]:
        topic_terms = self._topic_terms(topic)
        posts: List[FeedItem] = []
        for item in items:
            if not self._matches_topic(topic_terms, item.title, ""):
                continue
            posts.append(item)
            if len(posts) >= self.limit:
                break
        return posts

    @staticmethod
    def _topic_terms(topic: str) -> List[str]:
        return _topic_terms(topic)

    @staticmethod
    def _text(item: ET.Element, tag: str) -> str:
        value = item.findtext(tag, default="")
        return html.unescape(value.strip())

    @staticmethod
    def _parse_pub_date(pub_date: str) -> int:
        if not pub_date:
            return 0
        try:
            return int(parsedate_to_datetime(pub_date).astimezone(timezone.utc).timestamp())
        except (TypeError, ValueError, IndexError, OverflowError):
            return 0

    @staticmethod
    def _strip_html(value: str) -> str:
        return html.unescape(re.sub(r"<[^>]+>", " ", value))

    def _matches_topic(self, topic_terms: List[str], title: str, content: str) -> bool:
        haystack = f"{title} {self._strip_html(content)}".lower()
        terms, strict_all = _topic_match_terms(topic_terms)
        return _matches_topic_terms(terms, haystack, strict_all=strict_all)
