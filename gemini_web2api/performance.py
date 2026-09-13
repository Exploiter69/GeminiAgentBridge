"""Performance and stability helpers for Phase 12.

The helpers are deliberately deterministic: no jitter, no hidden caching of
model responses, and no changes to downstream tool execution semantics.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from time import perf_counter
from typing import Callable, Iterable, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class RetryPolicy:
    """Bounded exponential retry policy with a deterministic delay sequence."""

    attempts: int = 3
    base_delay_sec: float = 2.0
    backoff_multiplier: float = 2.0
    max_delay_sec: float = 30.0

    def __post_init__(self) -> None:
        if self.attempts < 1:
            raise ValueError("attempts must be >= 1")
        if self.base_delay_sec < 0:
            raise ValueError("base_delay_sec must be >= 0")
        if self.backoff_multiplier < 1:
            raise ValueError("backoff_multiplier must be >= 1")
        if self.max_delay_sec < 0:
            raise ValueError("max_delay_sec must be >= 0")

    def delay_for_retry(self, retry_index: int) -> float:
        """Return the delay before retry ``retry_index`` (zero-based)."""
        if retry_index < 0:
            raise ValueError("retry_index must be >= 0")
        delay = self.base_delay_sec * (self.backoff_multiplier ** retry_index)
        return min(delay, self.max_delay_sec)


@dataclass(frozen=True)
class TimingSample:
    name: str
    samples: tuple[float, ...]

    @property
    def median_ms(self) -> float:
        return median(self.samples) * 1000.0 if self.samples else 0.0

    @property
    def total_ms(self) -> float:
        return sum(self.samples) * 1000.0


def benchmark_callable(name: str, fn: Callable[[], T], iterations: int = 25) -> tuple[T, TimingSample]:
    """Run a deterministic micro-benchmark and return the last value + timing."""
    if iterations < 1:
        raise ValueError("iterations must be >= 1")
    samples: list[float] = []
    value: T
    for _ in range(iterations):
        start = perf_counter()
        value = fn()
        samples.append(perf_counter() - start)
    return value, TimingSample(name=name, samples=tuple(samples))


def percentile(values: Iterable[float], fraction: float) -> float:
    """Compute a linear-interpolated percentile without external dependencies."""
    data = sorted(float(v) for v in values)
    if not data:
        return 0.0
    if not 0.0 <= fraction <= 1.0:
        raise ValueError("fraction must be between 0 and 1")
    if len(data) == 1:
        return data[0]
    position = (len(data) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(data) - 1)
    weight = position - lower
    return data[lower] + (data[upper] - data[lower]) * weight


def stable_report(samples: Iterable[TimingSample]) -> dict[str, dict[str, float]]:
    """Return JSON-friendly timing facts without imposing machine-specific limits."""
    report: dict[str, dict[str, float]] = {}
    for sample in samples:
        report[sample.name] = {
            "iterations": float(len(sample.samples)),
            "median_ms": sample.median_ms,
            "p95_ms": percentile(sample.samples, 0.95) * 1000.0,
            "total_ms": sample.total_ms,
        }
    return report
