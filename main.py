from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import mean

from trendbot.analyzer import Alert, analyze_topic
from trendbot.config import load_config
from trendbot.fetchers import GoogleNewsFetcher, RedditFetcher
from trendbot.notifier import DiscordNotifier
from trendbot.storage import Observation, Storage
from trendbot.trends import extract_trend_signal


def log(message: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{stamp}] {message}", flush=True)


def _contains_blocked_term(text: str, blocked_terms: list[str]) -> bool:
    lowered = text.lower()
    return any(term and term.lower() in lowered for term in blocked_terms)


def _topic_thresholds(topic: str, config):
    lowered = topic.lower()
    if "pop culture" in lowered or "celebrity" in lowered:
        return config.pop_culture_spike_multiplier, config.pop_culture_min_baseline
    return config.spike_multiplier, config.min_baseline


@dataclass(frozen=True)
class ClosestCandidate:
    topic: str
    source: str
    score: float
    current: int
    threshold: float
    baseline: float


def _trigger_score(current: int, baseline: float, multiplier: float, min_baseline: int) -> tuple[float, float]:
    if baseline < min_baseline:
        return 0.0, max(float(min_baseline), baseline * multiplier)
    threshold = max(float(min_baseline), baseline * multiplier)
    if threshold <= 0:
        return 0.0, threshold
    return current / threshold, threshold


def poll_once() -> int:
    config = load_config()
    if not config.topics:
        raise SystemExit("Set TRENDBOT_TOPICS to at least one topic.")
    reddit_topics = config.topics[: max(0, config.reddit_topic_limit)]

    storage = Storage(config.db_path)
    fetchers = [
        GoogleNewsFetcher(
            limit=config.reddit_limit,
            timeout_seconds=config.reddit_timeout_seconds,
            hl=config.google_news_hl,
            gl=config.google_news_gl,
            ceid=config.google_news_ceid,
        ),
    ]
    if config.reddit_enabled:
        fetchers.insert(
            0,
            RedditFetcher(
                limit=config.reddit_limit,
                timeout_seconds=config.reddit_timeout_seconds,
                subreddits=config.reddit_subreddits,
            ),
        )

    notifier = None
    if config.discord_webhook_url:
        notifier = DiscordNotifier(config.discord_webhook_url, config.reddit_timeout_seconds)

    alerts_sent = 0
    now = int(time.time())
    closest_candidate: ClosestCandidate | None = None

    for topic in config.topics:
        topic_spike_multiplier, topic_min_baseline = _topic_thresholds(topic, config)
        new_posts_by_source: dict[str, list] = {}
        triggering_alerts: list[Alert] = []
        for fetcher in fetchers:
            if fetcher.source_name == "reddit" and topic not in reddit_topics:
                continue
            try:
                posts = fetcher.search(topic)
            except Exception as exc:
                if fetcher.source_name == "reddit":
                    continue
                log(f"{fetcher.source_name} fetch failed for {topic!r}: {exc}")
                continue

            new_posts = []
            for post in posts:
                if _contains_blocked_term(f"{post.title} {post.url}", config.blocked_terms):
                    continue
                if not storage.has_seen_item(fetcher.source_name, topic, post.id):
                    new_posts.append(post)

            if new_posts:
                storage.mark_seen_items(fetcher.source_name, topic, (post.id for post in new_posts))
            new_posts_by_source[fetcher.source_name] = new_posts

            observation = Observation(
                topic=topic,
                source=fetcher.source_name,
                observed_at=now,
                new_mentions=len(new_posts),
            )
            storage.add_observation(observation)

            history = storage.recent_observations(
                topic=topic,
                source=fetcher.source_name,
                limit=config.window_size + 1,
            )
            previous_values = [obs.new_mentions for obs in history[:-1]]
            baseline = mean(previous_values[-config.window_size:]) if previous_values else 0.0
            alert = analyze_topic(
                topic=topic,
                source=fetcher.source_name,
                observations=history,
                window_size=config.window_size,
                spike_multiplier=topic_spike_multiplier,
                min_baseline=topic_min_baseline,
            )
            score, threshold = _trigger_score(
                current=len(new_posts),
                baseline=baseline,
                multiplier=topic_spike_multiplier,
                min_baseline=topic_min_baseline,
            )
            if score < 1.0 and (closest_candidate is None or score > closest_candidate.score):
                closest_candidate = ClosestCandidate(
                    topic=topic,
                    source=fetcher.source_name,
                    score=score,
                    current=len(new_posts),
                    threshold=threshold,
                    baseline=baseline,
                )

            log(
                f"{topic!r} [{fetcher.source_name}]: +{len(new_posts)} filtered matches "
                f"({len(posts)} fetched)"
            )

            if alert:
                triggering_alerts.append(alert)

        if triggering_alerts and notifier:
            strongest_alert = max(
                triggering_alerts,
                key=lambda item: item.current / item.baseline if item.baseline else float("inf"),
            )
            google_signal = extract_trend_signal(
                new_posts_by_source.get("google_news", []),
                config.blocked_terms,
                "google_news",
            )
            reddit_signal = extract_trend_signal(
                new_posts_by_source.get("reddit", []),
                config.blocked_terms,
                "reddit",
            )
            if google_signal and google_signal.score >= 1:
                trend_signal = google_signal
            elif reddit_signal:
                trend_signal = reddit_signal
            else:
                combined_posts = []
                for posts in new_posts_by_source.values():
                    combined_posts.extend(posts)
                trend_signal = extract_trend_signal(combined_posts, config.blocked_terms, strongest_alert.source)
            alert_topic = trend_signal.label if trend_signal else topic
            alert_headline = trend_signal.example_title if trend_signal else ""
            combined_source = " + ".join(sorted({item.source for item in triggering_alerts}))
            try:
                notifier.send_alert(
                    Alert(
                        topic=alert_topic,
                        current=strongest_alert.current,
                        baseline=strongest_alert.baseline,
                        multiplier=strongest_alert.multiplier,
                        source=combined_source,
                        headline=alert_headline,
                    )
                )
                alerts_sent += 1
                log(f"discord alert sent for {alert_topic!r} [{combined_source}]")
            except Exception as exc:
                log(f"discord alert failed for {alert_topic!r} [{combined_source}]: {exc}")

    if config.debug_mode:
        if closest_candidate:
            log(
                "debug closest-to-trigger: "
                f"{closest_candidate.topic!r} [{closest_candidate.source}] "
                f"score={closest_candidate.score:.2f} current={closest_candidate.current} "
                f"threshold={closest_candidate.threshold:.2f} baseline={closest_candidate.baseline:.2f}"
            )
        else:
            log("debug closest-to-trigger: no eligible near-spike candidate this run")

    return alerts_sent


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "once":
        config = load_config()
        alerts_sent = poll_once()
        if config.debug_mode:
            log(f"debug one-shot completed with {alerts_sent} alert(s)")
        return

    config = load_config()
    notifier = DiscordNotifier(config.discord_webhook_url, config.reddit_timeout_seconds) if config.discord_webhook_url else None
    last_heartbeat_at = int(time.time())
    log(
        "starting trendbot with "
        f"{len(config.topics)} topics, interval {config.poll_interval_seconds}s"
    )
    while True:
        alerts_sent = poll_once()
        now = int(time.time())
        if notifier and now - last_heartbeat_at >= config.heartbeat_interval_seconds:
            try:
                heartbeat_message = (
                    f"TrendBot heartbeat: still running, checked {len(config.topics)} topics"
                )
                if alerts_sent == 0:
                    heartbeat_message += ", no alerts in the last check."
                else:
                    heartbeat_message += f", sent {alerts_sent} alert(s) in the last check."
                notifier.send_heartbeat(heartbeat_message)
                last_heartbeat_at = now
                log("heartbeat sent")
            except Exception as exc:
                log(f"heartbeat failed: {exc}")
        time.sleep(config.poll_interval_seconds)


if __name__ == "__main__":
    main()
