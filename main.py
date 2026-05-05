from __future__ import annotations

import sys
import time
import re
import os
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import mean

from trendbot.analyzer import Alert, analyze_topic, score_trend
from trendbot.categories import categorize_topic
from trendbot.config import load_config
from trendbot.dashboard import DashboardServer, write_snapshot_file
from trendbot.fetchers import GoogleNewsFetcher, RSSFetcher, RedditFetcher
from trendbot.notifier import DiscordNotifier
from trendbot.storage import Observation, Storage, TopicRollup
from trendbot.trends import choose_alert_topic, dedupe_feed_items, extract_trend_signal, normalize_cluster_key

SOURCE_SCOPE: dict[str, str] = {
    "google_news_se": "sweden",
    "aftonbladet_noje": "sweden",
    "expressen_noje": "sweden",
    "hant": "sweden",
    "hant_extra": "sweden",
    "svt_noje": "sweden",
    "tv4_noje": "sweden",
    "google_news_global": "global",
    "bbc_entertainment": "global",
    "npr_music": "global",
    "ap_entertainment": "global",
    "variety": "global",
    "billboard": "global",
    "the_verge": "global",
    "people": "global",
    "eonline": "global",
    "tmz": "global",
    "rolling_stone": "global",
    "reddit": "global",
    "tiktok_web": "global",
}


def log(message: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{stamp}] {message}", flush=True)


def _contains_blocked_term(text: str, blocked_terms: list[str]) -> bool:
    lowered = text.lower()
    return any(term and term.lower() in lowered for term in blocked_terms)


def _looks_like_previous_year_story(text: str, current_year: int) -> bool:
    years = [int(match) for match in re.findall(r"\b(20\d{2})\b", text)]
    if not years:
        return False
    return max(years) < current_year


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


def _build_fetchers(config):
    recency_suffix = config.google_news_recency_query
    fetchers = []

    if config.enable_source_google_se:
        google_news_se = GoogleNewsFetcher(
            limit=config.reddit_limit,
            timeout_seconds=config.reddit_timeout_seconds,
            hl=config.google_news_hl,
            gl=config.google_news_gl,
            ceid=config.google_news_ceid,
            query_suffix=recency_suffix,
        )
        google_news_se.source_name = "google_news_se"
        fetchers.append(google_news_se)

    if config.enable_source_google_global:
        google_news_global = GoogleNewsFetcher(
            limit=config.reddit_limit,
            timeout_seconds=config.reddit_timeout_seconds,
            hl="en-US",
            gl="US",
            ceid="US:en",
            query_suffix=recency_suffix,
        )
        google_news_global.source_name = "google_news_global"
        fetchers.append(google_news_global)

    if config.enable_source_bbc:
        fetchers.append(
            RSSFetcher(
                source_name="bbc_entertainment",
                feed_url="https://feeds.bbci.co.uk/news/entertainment_and_arts/rss.xml",
                limit=config.reddit_limit,
                timeout_seconds=config.reddit_timeout_seconds,
                refresh_seconds=config.rss_refresh_seconds,
            )
        )
    if config.enable_source_npr:
        fetchers.append(
            RSSFetcher(
                source_name="npr_music",
                feed_url="https://feeds.npr.org/1039/rss.xml",
                limit=config.reddit_limit,
                timeout_seconds=config.reddit_timeout_seconds,
                refresh_seconds=config.rss_refresh_seconds,
            )
        )
    if config.enable_source_ap:
        fetchers.append(
            RSSFetcher(
                source_name="ap_entertainment",
                feed_url="https://apnews.com/hub/entertainment?output=rss",
                limit=config.reddit_limit,
                timeout_seconds=config.reddit_timeout_seconds,
                refresh_seconds=config.rss_refresh_seconds,
            )
        )
    if config.enable_source_variety:
        fetchers.append(
            RSSFetcher(
                source_name="variety",
                feed_url="https://variety.com/feed/",
                limit=config.reddit_limit,
                timeout_seconds=config.reddit_timeout_seconds,
                refresh_seconds=config.rss_refresh_seconds,
            )
        )
    if config.enable_source_billboard:
        fetchers.append(
            RSSFetcher(
                source_name="billboard",
                feed_url="https://www.billboard.com/feed/",
                limit=config.reddit_limit,
                timeout_seconds=config.reddit_timeout_seconds,
                refresh_seconds=config.rss_refresh_seconds,
            )
        )
    if config.enable_source_the_verge:
        fetchers.append(
            RSSFetcher(
                source_name="the_verge",
                feed_url="https://www.theverge.com/rss/index.xml",
                limit=config.reddit_limit,
                timeout_seconds=config.reddit_timeout_seconds,
                refresh_seconds=config.rss_refresh_seconds,
            )
        )
    if config.enable_source_people:
        fetchers.append(
            RSSFetcher(
                source_name="people",
                feed_url="https://people.com/feed/",
                limit=config.reddit_limit,
                timeout_seconds=config.reddit_timeout_seconds,
                refresh_seconds=config.rss_refresh_seconds,
            )
        )
    if config.enable_source_eonline:
        fetchers.append(
            RSSFetcher(
                source_name="eonline",
                feed_url="https://www.eonline.com/syndication/feeds/rssfeeds/topstories.xml",
                limit=config.reddit_limit,
                timeout_seconds=config.reddit_timeout_seconds,
                refresh_seconds=config.rss_refresh_seconds,
            )
        )
    if config.enable_source_tmz:
        fetchers.append(
            RSSFetcher(
                source_name="tmz",
                feed_url="https://www.tmz.com/rss.xml",
                limit=config.reddit_limit,
                timeout_seconds=config.reddit_timeout_seconds,
                refresh_seconds=config.rss_refresh_seconds,
            )
        )
    if config.enable_source_rollingstone:
        fetchers.append(
            RSSFetcher(
                source_name="rolling_stone",
                feed_url="https://www.rollingstone.com/feed/",
                limit=config.reddit_limit,
                timeout_seconds=config.reddit_timeout_seconds,
                refresh_seconds=config.rss_refresh_seconds,
            )
        )
    if config.enable_source_aftonbladet:
        aftonbladet = GoogleNewsFetcher(
            limit=config.reddit_limit,
            timeout_seconds=config.reddit_timeout_seconds,
            hl="sv-SE",
            gl="SE",
            ceid="SE:sv",
            query_suffix=f"site:aftonbladet.se nöje {recency_suffix}".strip(),
        )
        aftonbladet.source_name = "aftonbladet_noje"
        fetchers.append(aftonbladet)
    if config.enable_source_expressen:
        expressen = GoogleNewsFetcher(
            limit=config.reddit_limit,
            timeout_seconds=config.reddit_timeout_seconds,
            hl="sv-SE",
            gl="SE",
            ceid="SE:sv",
            query_suffix=f"site:expressen.se nöje {recency_suffix}".strip(),
        )
        expressen.source_name = "expressen_noje"
        fetchers.append(expressen)
    if config.enable_source_hant:
        hant = GoogleNewsFetcher(
            limit=config.reddit_limit,
            timeout_seconds=config.reddit_timeout_seconds,
            hl="sv-SE",
            gl="SE",
            ceid="SE:sv",
            query_suffix=f"site:hant.se {recency_suffix}".strip(),
        )
        hant.source_name = "hant"
        fetchers.append(hant)
    if config.enable_source_hant_extra:
        hant_extra = GoogleNewsFetcher(
            limit=config.reddit_limit,
            timeout_seconds=config.reddit_timeout_seconds,
            hl="sv-SE",
            gl="SE",
            ceid="SE:sv",
            query_suffix=f"site:hant.se \"hänt extra\" nöje {recency_suffix}".strip(),
        )
        hant_extra.source_name = "hant_extra"
        fetchers.append(hant_extra)
    if config.enable_source_svt:
        svt = GoogleNewsFetcher(
            limit=config.reddit_limit,
            timeout_seconds=config.reddit_timeout_seconds,
            hl="sv-SE",
            gl="SE",
            ceid="SE:sv",
            query_suffix=f"site:svt.se tv serie underhållning {recency_suffix}".strip(),
        )
        svt.source_name = "svt_noje"
        fetchers.append(svt)
    if config.enable_source_tv4:
        tv4 = GoogleNewsFetcher(
            limit=config.reddit_limit,
            timeout_seconds=config.reddit_timeout_seconds,
            hl="sv-SE",
            gl="SE",
            ceid="SE:sv",
            query_suffix=f"site:tv4.se nöje tv program {recency_suffix}".strip(),
        )
        tv4.source_name = "tv4_noje"
        fetchers.append(tv4)
    if config.enable_source_tiktok:
        tiktok = GoogleNewsFetcher(
            limit=config.reddit_limit,
            timeout_seconds=config.reddit_timeout_seconds,
            hl="en-US",
            gl="US",
            ceid="US:en",
            query_suffix=f"site:tiktok.com {recency_suffix}".strip(),
        )
        tiktok.source_name = "tiktok_web"
        fetchers.append(tiktok)
    if config.reddit_enabled:
        fetchers.insert(
            0,
            RedditFetcher(
                limit=config.reddit_limit,
                timeout_seconds=config.reddit_timeout_seconds,
                subreddits=config.reddit_subreddits,
                refresh_seconds=config.reddit_refresh_seconds,
                request_delay_seconds=config.reddit_request_delay_seconds,
                backoff_seconds=config.reddit_backoff_seconds,
            ),
        )
    return fetchers


def _infer_market_scope(new_posts_by_source: dict[str, list]) -> str:
    scopes = {
        SOURCE_SCOPE.get(source, "global")
        for source, posts in new_posts_by_source.items()
        if posts
    }
    if not scopes:
        return "mixed"
    if len(scopes) == 1:
        return next(iter(scopes))
    return "mixed"


def poll_once(config=None, storage=None) -> int:
    config = config or load_config()
    if not config.topics:
        raise SystemExit("Set TRENDBOT_TOPICS to at least one topic.")
    reddit_topics = config.topics[: max(0, config.reddit_topic_limit)]

    storage = storage or Storage(config.db_path)
    fetchers = _build_fetchers(config)

    notifier = None
    if config.discord_webhook_url:
        notifier = DiscordNotifier(config.discord_webhook_url, config.reddit_timeout_seconds)

    alerts_sent = 0
    now = int(time.time())
    current_year = datetime.now(timezone.utc).year
    oldest_allowed = now - (max(1, config.max_item_age_hours) * 3600)
    closest_candidate: ClosestCandidate | None = None

    for topic in config.topics:
        topic_spike_multiplier, topic_min_baseline = _topic_thresholds(topic, config)
        new_posts_by_source: dict[str, list] = {}
        triggering_alerts: list[Alert] = []
        baselines_by_source: list[float] = []
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
                if config.require_item_timestamp and post.created_utc <= 0:
                    continue
                if post.created_utc and post.created_utc < oldest_allowed:
                    continue
                if config.skip_previous_year_titles and _looks_like_previous_year_story(
                    f"{post.title} {post.summary}",
                    current_year,
                ):
                    continue
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
                fetched_mentions=len(posts),
            )
            storage.add_observation(observation)

            history = storage.recent_observations(
                topic=topic,
                source=fetcher.source_name,
                limit=config.window_size + 1,
            )
            previous_values = [obs.new_mentions for obs in history[:-1]]
            baseline = mean(previous_values[-config.window_size:]) if previous_values else 0.0
            baselines_by_source.append(baseline)
            alert = analyze_topic(
                topic=topic,
                source=fetcher.source_name,
                observations=history,
                window_size=config.window_size,
                spike_multiplier=topic_spike_multiplier,
                min_baseline=topic_min_baseline,
            )
            if alert and alert.ratio < config.alert_ratio_threshold:
                alert = None
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

        combined_posts = []
        for posts in new_posts_by_source.values():
            combined_posts.extend(posts)
        combined_posts = dedupe_feed_items(combined_posts, config.blocked_terms)
        source_count = sum(1 for posts in new_posts_by_source.values() if posts)
        cluster_signal = extract_trend_signal(combined_posts, config.blocked_terms, topic)
        cluster_label = cluster_signal.label if cluster_signal else topic
        cluster_key = normalize_cluster_key(cluster_label)
        combined_mentions = len(combined_posts)
        combined_baseline = mean(baselines_by_source) if baselines_by_source else 0.0
        signal_strength = float(cluster_signal.score) if cluster_signal else 0.0
        rollup_score = score_trend(
            current=combined_mentions,
            baseline=combined_baseline,
            source_count=source_count,
            signal_strength=signal_strength,
        )
        storage.add_topic_rollup(
            TopicRollup(
                topic=topic,
                observed_at=now,
                total_mentions=combined_mentions,
                source_count=source_count,
                category=categorize_topic(
                    " ".join(
                        part
                        for part in (
                            cluster_label,
                            cluster_signal.example_title if cluster_signal else "",
                            topic,
                        )
                        if part
                    )
                ),
                cluster_key=cluster_key,
                cluster_label=cluster_label,
                trend_score=rollup_score,
                example_title=cluster_signal.example_title if cluster_signal else "",
                market_scope=_infer_market_scope(new_posts_by_source),
            )
        )

        last_alert_key = f"last_alert_at:{topic}"
        last_alert_at_raw = storage.get_state(last_alert_key)
        last_alert_at = int(last_alert_at_raw) if last_alert_at_raw else 0
        cooldown_elapsed = now - last_alert_at >= config.alert_cooldown_seconds
        last_global_alert_at_raw = storage.get_state("last_alert_global_at")
        last_global_alert_at = int(last_global_alert_at_raw) if last_global_alert_at_raw else 0
        global_cooldown_elapsed = (
            config.alert_global_cooldown_seconds <= 0
            or now - last_global_alert_at >= config.alert_global_cooldown_seconds
        )

        if (
            triggering_alerts
            and notifier
            and len(triggering_alerts) >= config.alert_min_sources
            and cooldown_elapsed
            and global_cooldown_elapsed
        ):
            strongest_alert = max(
                triggering_alerts,
                key=lambda item: item.current / item.baseline if item.baseline else float("inf"),
            )
            google_global_signal = extract_trend_signal(
                new_posts_by_source.get("google_news_global", []),
                config.blocked_terms,
                "google_news_global",
            )
            google_se_signal = extract_trend_signal(
                new_posts_by_source.get("google_news_se", []),
                config.blocked_terms,
                "google_news_se",
            )
            # Prefer global angle when available, fall back to Swedish and then combined.
            if google_global_signal and google_global_signal.score >= 1:
                google_signal = google_global_signal
            elif google_se_signal and google_se_signal.score >= 1:
                google_signal = google_se_signal
            else:
                google_posts = []
                google_posts.extend(new_posts_by_source.get("google_news_global", []))
                google_posts.extend(new_posts_by_source.get("google_news_se", []))
                google_signal = extract_trend_signal(
                    google_posts,
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
            alert_topic, alert_headline = choose_alert_topic(trend_signal, topic)
            semantic_key = f"last_alert_semantic_at:{normalize_cluster_key(alert_topic)}"
            last_semantic_raw = storage.get_state(semantic_key)
            last_semantic_at = int(last_semantic_raw) if last_semantic_raw else 0
            semantic_cooldown_elapsed = now - last_semantic_at >= config.alert_cooldown_seconds
            if not semantic_cooldown_elapsed:
                if config.debug_mode:
                    log(f"debug skipped duplicate semantic alert for {alert_topic!r}")
                continue
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
                        source_count=source_count,
                        cluster_label=cluster_label,
                    )
                )
                storage.add_alert_event(
                    topic=alert_topic,
                    source=combined_source,
                    sent_at=now,
                    trend_score=strongest_alert.trend_score,
                )
                storage.set_state(last_alert_key, str(now))
                storage.set_state(semantic_key, str(now))
                storage.set_state("last_alert_global_at", str(now))
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


def update_snapshot(storage: Storage, config) -> None:
    try:
        write_snapshot_file(
            storage,
            config.dashboard_snapshot_path,
            settings={
                "window_size": config.window_size,
                "spike_multiplier": config.spike_multiplier,
                "min_baseline": config.min_baseline,
                "pop_culture_spike_multiplier": config.pop_culture_spike_multiplier,
                "pop_culture_min_baseline": config.pop_culture_min_baseline,
                "daily_series_bucket_seconds": config.daily_series_bucket_seconds,
                "daily_series_window_seconds": config.daily_series_window_seconds,
                "alert_count_offset": config.alert_count_offset,
                "blocked_terms": config.blocked_terms,
                "dashboard_admin_password": os.getenv("DASHBOARD_ADMIN_PASSWORD", "").strip(),
                "dashboard_start_password": os.getenv("DASHBOARD_START_PASSWORD", "").strip(),
                "dashboard_pro_password": os.getenv("DASHBOARD_PRO_PASSWORD", "").strip(),
            },
        )
    except Exception as exc:
        log(f"dashboard snapshot failed: {exc}")


def main() -> None:
    # Ensure relative paths (.env, sqlite, snapshot) resolve from project folder.
    os.chdir(Path(__file__).resolve().parent)
    if len(sys.argv) > 1 and sys.argv[1] == "once":
        config = load_config()
        storage = Storage(config.db_path)
        alerts_sent = poll_once(config=config, storage=storage)
        update_snapshot(storage, config)
        if config.debug_mode:
            log(f"debug one-shot completed with {alerts_sent} alert(s)")
        return

    config = load_config()
    storage = Storage(config.db_path)
    notifier = DiscordNotifier(config.discord_webhook_url, config.reddit_timeout_seconds) if config.discord_webhook_url else None
    posts_notifier = None
    if config.discord_posts_webhook_url:
        posts_notifier = DiscordNotifier(config.discord_posts_webhook_url, config.reddit_timeout_seconds)
    elif notifier:
        posts_notifier = notifier
    dashboard = None
    if config.dashboard_enabled:
        try:
            dashboard = DashboardServer(
                storage,
                host=config.dashboard_host,
                port=config.dashboard_port,
                settings={
                    "window_size": config.window_size,
                    "spike_multiplier": config.spike_multiplier,
                    "min_baseline": config.min_baseline,
                    "pop_culture_spike_multiplier": config.pop_culture_spike_multiplier,
                    "pop_culture_min_baseline": config.pop_culture_min_baseline,
                    "daily_series_bucket_seconds": config.daily_series_bucket_seconds,
                    "daily_series_window_seconds": config.daily_series_window_seconds,
                    "alert_count_offset": config.alert_count_offset,
                    "blocked_terms": config.blocked_terms,
                    "dashboard_admin_password": os.getenv("DASHBOARD_ADMIN_PASSWORD", "").strip(),
                    "dashboard_start_password": os.getenv("DASHBOARD_START_PASSWORD", "").strip(),
                    "dashboard_pro_password": os.getenv("DASHBOARD_PRO_PASSWORD", "").strip(),
                },
            )
            dashboard.start()
            log(f"dashboard running at http://{config.dashboard_host}:{config.dashboard_port}")
        except OSError as exc:
            dashboard = None
            log(
                "dashboard disabled: "
                f"could not bind {config.dashboard_host}:{config.dashboard_port} ({exc})"
            )
    update_snapshot(storage, config)
    last_heartbeat_at = int(time.time())
    startup_now = int(time.time())
    last_daily_digest_at = int(storage.get_state("last_daily_digest_at") or startup_now)
    log(
        "starting trendbot with "
        f"{len(config.topics)} topics, interval {config.poll_interval_seconds}s"
    )
    while True:
        alerts_sent = poll_once(config=config, storage=storage)
        update_snapshot(storage, config)
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
        if notifier and now - last_daily_digest_at >= config.daily_digest_interval_seconds:
            top_topics = storage.top_topics_since(now - 86400, 10)
            if top_topics:
                lines = []
                for idx, item in enumerate(top_topics, start=1):
                    label = item.cluster_label or item.topic
                    about = f" — about {item.example_title}" if getattr(item, "example_title", "") else ""
                    lines.append(
                        f"{idx}. {label} - {item.total_mentions} mentions ({item.samples} samples){about}"
                    )
                try:
                    notifier.send_embed(
                        content="TrendBot daily top 10",
                        title="Daily Top 10",
                        description="\n".join(lines),
                        color=0xF59E0B,
                        mention=False,
                    )
                    storage.set_state("last_daily_digest_at", str(now))
                    last_daily_digest_at = now
                    log("daily top 10 sent")
                    if posts_notifier:
                        posts_notifier.send_posts_ideas(top_topics[:5])
                        log("daily #posts ideas sent")
                except Exception as exc:
                    log(f"daily top 10 failed: {exc}")
        time.sleep(config.poll_interval_seconds)


if __name__ == "__main__":
    main()
