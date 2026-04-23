from __future__ import annotations

import json
import urllib.parse
import urllib.request
import urllib.error
from dataclasses import dataclass

from .analyzer import Alert


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

    def send_alert(self, alert: Alert) -> None:
        topic = alert.topic.strip()
        about_line = f"About: {alert.headline or topic}"
        topic_link = self._topic_link(topic)
        suggestion = self._suggest_response(topic, alert.headline)
        self.send_embed(
            content=f'@everyone attention "{topic}" is popular right now',
            title=f'"{topic}" is popular right now',
            description=(
                f"Source: {alert.source}\n"
                f"{about_line}\n"
                f"Link: {topic_link}\n"
                f"Current mentions: {alert.current}\n"
                f"Baseline: {alert.baseline:.2f}\n"
                f"Spike threshold: {alert.multiplier:.2f}x\n"
                f"{suggestion}"
            ),
            color=16753920,
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
