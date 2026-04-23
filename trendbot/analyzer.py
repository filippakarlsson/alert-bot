from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import List, Optional

from .storage import Observation


@dataclass(frozen=True)
class Alert:
    topic: str
    current: int
    baseline: float
    multiplier: float
    source: str
    headline: str = ""

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
        return None

    if current >= max(min_baseline, int(baseline * spike_multiplier)):
        return Alert(
            topic=topic,
            current=current,
            baseline=baseline,
            multiplier=spike_multiplier,
            source=source,
        )
    return None
