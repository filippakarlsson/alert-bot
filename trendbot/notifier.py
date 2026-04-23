from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
import urllib.error
from dataclasses import dataclass

from .analyzer import Alert
from .categories import category_color


@dataclass(frozen=True)
class DiscordNotifier:
    webhook_url: str
    timeout_seconds: int = 15

    def _topic_link(self, topic: str) -> str:
        query = urllib.parse.quote_plus(topic.strip())
        return f"https://news.google.com/search?q={query}"

    def _suggest_response(self, topic: str, headline: str) -> str:
        focus = headline.strip() or topic.strip()
        text = f"{topic} {headline}".lower()
        if any(word in text for word in {"k-pop", "music", "eurovision", "album", "song", "tour"}):
            return f"Example reply: '{focus} feels like the kind of music story people will keep talking about all day.'"
        if any(word in text for word in {"movie", "movies", "tv", "episode", "season", "trailer", "celebrity", "pop culture"}):
            return f"Example reply: '{focus} is a proper pop culture moment, so I can see this taking over the conversation.'"
        if any(word in text for word in {"politics", "election", "government", "congress", "president", "news"}):
            return f"Example reply: '{focus} looks like a serious talking point that people will keep debating.'"
        if any(word in text for word in {"tiktok", "viral", "memes", "internet culture", "streamer", "streamers", "youtube", "influencer", "creator"}):
            return f"Example reply: '{focus} feels like exactly the kind of internet moment that spreads everywhere fast.'"
        if any(word in text for word in {"gaming", "game", "games", "esports"}):
            return f"Example reply: '{focus} is the kind of gaming topic that gets people arguing immediately.'"
        return f"Example reply: '{focus} is clearly gaining traction, and I can see why people are reacting to it.'"

    def _postability_score(self, alert: Alert) -> int:
        topic = (alert.topic or "").strip()
        headline = (alert.headline or "").strip()
        text = f"{topic} {headline}"
        tokens = [token for token in re.split(r"\s+", topic) if token]
        ratio = alert.ratio if alert.baseline > 0 else float(alert.current)

        score = 35
        score += min(25, int(alert.trend_score * 0.25))
        score += min(12, int(alert.source_count * 4))
        score += min(15, int(max(0.0, ratio) * 3))

        if len(tokens) >= 3:
            score += 8
        if any(ch.isdigit() for ch in text):
            score += 4
        if any(token[:1].isupper() for token in tokens):
            score += 6
        if headline:
            score += 5
        if len(topic) < 8:
            score -= 6

        return max(0, min(100, score))

    def _auto_brief(self, alert: Alert, topic_link: str) -> str:
        topic = alert.topic.strip()
        focus = (alert.headline or topic).strip()
        ratio = alert.ratio if alert.baseline > 0 else float(alert.current)
        momentum = "high" if ratio >= 2.0 else ("medium" if ratio >= 1.3 else "emerging")

        what_happened = f"What happened: {focus}."
        why_trending = (
            f"Why trending: {alert.current} new mentions vs {alert.baseline:.2f} baseline "
            f"({ratio:.2f}x), {alert.source_count} source(s), momentum {momentum}."
        )
        content_angle = (
            f"Content angle: Lead with '{topic}' + one concrete detail from the headline, "
            "then ask a reaction question to drive comments."
        )
        first_line = f"Possible opener: '{topic} is blowing up right now - here's why.'"

        return (
            f"{what_happened}\n"
            f"{why_trending}\n"
            f"{content_angle}\n"
            f"{first_line}\n"
            f"Reference: {topic_link}"
        )

    def _reaction_potential(self, text: str) -> int:
        value = (text or "").lower()
        strong_terms = {
            "chock", "skandal", "bråk", "rasar", "ilska", "drama", "storm",
            "feud", "backlash", "controversy", "scandal", "shocking", "outrage",
            "breakup", "anklag", "kritik", "läckt", "exposed",
        }
        medium_terms = {
            "avslöjar", "nytt", "premiär", "först", "reaktion", "omtalad",
            "viral", "trend", "snackis", "debate",
        }
        score = 35
        score += min(45, sum(1 for term in strong_terms if term in value) * 10)
        score += min(20, sum(1 for term in medium_terms if term in value) * 4)
        return max(0, min(100, score))

    def send_posts_ideas(self, top_topics: list) -> None:
        if not top_topics:
            return
        ranked = sorted(
            top_topics,
            key=lambda item: (
                self._reaction_potential(
                    f"{getattr(item, 'topic', '')} {getattr(item, 'example_title', '')}"
                ),
                getattr(item, "trend_score", 0.0),
                getattr(item, "total_mentions", 0),
            ),
            reverse=True,
        )[:3]
        lines = []
        for idx, item in enumerate(ranked, start=1):
            topic = getattr(item, "topic", "Trend")
            example = getattr(item, "example_title", "") or topic
            potential = self._reaction_potential(f"{topic} {example}")
            link = self._topic_link(topic)
            lines.append(
                f"{idx}. {topic} ({potential}/100 reaction potential)\n"
                f"Hook: {example}\n"
                f"Post idea: 'Alla pratar om {topic} just nu - vad tycker ni?'\n"
                f"Link: {link}"
            )
        self.send_embed(
            content="What to post today (#posts)",
            title="Dagens inläggsidéer",
            description="\n\n".join(lines),
            color=0x60A5FA,
            mention=False,
        )

    def send_alert(self, alert: Alert) -> None:
        topic = alert.topic.strip()
        about_line = f"About: {alert.headline or topic}"
        topic_link = self._topic_link(topic)
        suggestion = self._suggest_response(topic, alert.headline)
        postability_score = self._postability_score(alert)
        auto_brief = self._auto_brief(alert, topic_link)
        cluster_line = alert.cluster_label.strip() or topic
        self.send_embed(
            content=f'@everyone attention "{topic}" is popular right now',
            title=f'"{topic}" is popular right now',
            description=(
                f"Source: {alert.source}\n"
                f"Sources: {alert.source_count}\n"
                f"Category: {alert.category}\n"
                f"Cluster: {cluster_line}\n"
                f"Trend score: {alert.trend_score:.1f}/100\n"
                f"Postability score: {postability_score}/100\n"
                f"{about_line}\n"
                f"Link: {topic_link}\n"
                f"Current mentions: {alert.current}\n"
                f"Baseline: {alert.baseline:.2f}\n"
                f"Spike threshold: {alert.multiplier:.2f}x\n"
                f"{suggestion}\n\n"
                f"Auto-brief\n"
                f"{auto_brief}"
            ),
            color=category_color(alert.category),
            mention=True,
        )

    def send_embed(
        self,
        content: str,
        title: str,
        description: str,
        color: int = 16753920,
        mention: bool = False,
    ) -> None:
        body = {
            "username": "TrendBot",
            "content": content,
            "embeds": [
                {
                    "title": title,
                    "description": description,
                    "color": color,
                }
            ],
        }
        if mention:
            body["allowed_mentions"] = {"parse": ["everyone"]}
        self._post(body)

    def send_heartbeat(self, message: str) -> None:
        self.send_embed(
            content=message,
            title="TrendBot heartbeat",
            description=message,
            color=65280,
            mention=False,
        )

    def _post(self, body: dict) -> None:
        request = urllib.request.Request(
            self.webhook_url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 trendbot/0.1",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                if response.status not in (200, 204):
                    raise RuntimeError(f"discord returned unexpected status {response.status}")
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace").strip()
            raise RuntimeError(
                f"discord webhook failed: HTTP {exc.code}"
                + (f" - {details}" if details else "")
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"discord webhook network error: {exc.reason}") from exc
