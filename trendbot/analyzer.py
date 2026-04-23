from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import List, Optional

from .categories import categorize_topic
from .storage import Observation


@dataclass(frozen=True)
class Alert:
    topic: str
    current: int
    baseline: float
    multiplier: float
    source: str
    headline: str = ""
    category: str = "default"
    trend_score: float = 0.0
    source_count: int = 1
    cluster_label: str = ""

    @property
    def ratio(self) -> float:
        if self.baseline <= 0:
            return float("inf") if self.current > 0 else 0.0
        return self.current / self.baseline


def analyze_topic(
    topic: str,
    source: str,
    observations: List[Observation],
    window_size: int,
    spike_multiplier: float,
    min_baseline: int,
) -> Optional[Alert]:
    if not observations:
        return None

    current = observations[-1].new_mentions
    history = [obs.new_mentions for obs in observations[:-1]]
    if not history:
        return None

    baseline_window = history[-window_size:]
    baseline = mean(baseline_window) if baseline_window else 0.0
    if baseline < min_baseline:
        # Cold-start mode: allow alerts even when baseline is still near zero.
        cold_start_floor = max(2, min_baseline + 1)
        if current >= cold_start_floor:
            trend_score = score_trend(current=current, baseline=max(1.0, baseline))
            return Alert(
                topic=topic,
                current=current,
                baseline=max(1.0, baseline),
                multiplier=spike_multiplier,
                source=source,
                category=categorize_topic(topic),
                trend_score=trend_score,
            )
        return None

    if current >= max(min_baseline, int(baseline * spike_multiplier)):
        trend_score = score_trend(current=current, baseline=baseline)
        return Alert(
            topic=topic,
            current=current,
            baseline=baseline,
            multiplier=spike_multiplier,
            source=source,
            category=categorize_topic(topic),
            trend_score=trend_score,
        )
    return None


def score_trend(
    current: int,
    baseline: float,
    source_count: int = 1,
    signal_strength: float = 0.0,
    momentum: float = 0.0,
) -> float:
    if current <= 0:
        return 0.0
    ratio = current / baseline if baseline > 0 else float(current)
    raw_score = (
        (ratio * 16.0)
        + (current * 1.8)
        + (baseline * 1.25)
        + (source_count * 7.5)
        + (signal_strength * 1.5)
        + (momentum * 6.0)
    )
    return min(100.0, round(raw_score, 1))
