"""Region-aware duty cycle enforcement for LoRa transmission.

Tracks cumulative airtime over a rolling window and rejects
transmissions that would exceed the regulatory limit.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass

logger = logging.getLogger(__name__)

DUTY_CYCLE_LIMITS = {
    "US": 100.0,
    "EU_868": 1.0,
    "ANZ": 100.0,
    "IN": 100.0,
    "KR": 100.0,
    "SG_923": 100.0,
}

# Conservative out-of-the-box cap per region. Sits well under the
# regulatory ceiling for unrestricted bands (US/ANZ/KR/SG_923 have no
# duty cycle rule) and matches the regulatory cap for restricted ones
# (EU_868 and IN are 1%). Users can override in local.yaml.
MESHPOINT_DUTY_DEFAULTS = {
    "US": 10.0,
    "EU_868": 1.0,
    "ANZ": 10.0,
    "IN": 1.0,
    "KR": 10.0,
    "SG_923": 10.0,
}

DEFAULT_WINDOW_SECONDS = 3600


def resolve_max_duty_percent(region: str, configured: float | None) -> float:
    """Resolve the effective max duty cycle for a region.

    If the user set ``transmit.max_duty_cycle_percent`` in local.yaml,
    that value wins. Otherwise the regional Meshpoint default applies
    (10% in US/ANZ/KR/SG_923, 1% in EU_868/IN). Unknown regions fall
    back to a safe 1%.
    """
    if configured is not None:
        return configured
    return MESHPOINT_DUTY_DEFAULTS.get(region, 1.0)


@dataclass
class TxRecord:
    """Single transmission airtime record."""

    timestamp: float
    airtime_ms: int


class DutyCycleTracker:
    """Enforces regional duty cycle limits on LoRa transmissions.

    Maintains a sliding window of recent TX airtimes and computes
    the cumulative usage as a percentage of the window duration.
    """

    def __init__(
        self,
        region: str = "US",
        max_duty_percent: float | None = None,
        window_seconds: int = DEFAULT_WINDOW_SECONDS,
    ):
        self._region = region
        self._window_seconds = window_seconds
        self._max_duty_percent = (
            max_duty_percent
            if max_duty_percent is not None
            else DUTY_CYCLE_LIMITS.get(region, 1.0)
        )
        self._records: deque[TxRecord] = deque()

    @property
    def region(self) -> str:
        return self._region

    @property
    def max_duty_percent(self) -> float:
        return self._max_duty_percent

    def check_budget(self, airtime_ms: int) -> bool:
        """Return True if there is enough duty cycle budget for this TX."""
        self._prune_expired()
        current_ms = sum(r.airtime_ms for r in self._records)
        window_ms = self._window_seconds * 1000
        projected_percent = (current_ms + airtime_ms) / window_ms * 100
        return projected_percent <= self._max_duty_percent

    def record_tx(self, airtime_ms: int) -> None:
        """Log a completed transmission."""
        self._records.append(TxRecord(
            timestamp=time.monotonic(),
            airtime_ms=airtime_ms,
        ))
        self._log_usage()

    def current_usage_percent(self) -> float:
        """Current duty cycle usage as a percentage."""
        self._prune_expired()
        current_ms = sum(r.airtime_ms for r in self._records)
        window_ms = self._window_seconds * 1000
        return (current_ms / window_ms) * 100

    def remaining_budget_ms(self) -> int:
        """Milliseconds of airtime still available in the current window."""
        self._prune_expired()
        current_ms = sum(r.airtime_ms for r in self._records)
        window_ms = self._window_seconds * 1000
        max_ms = int(window_ms * self._max_duty_percent / 100)
        return max(0, max_ms - current_ms)

    def _prune_expired(self) -> None:
        """Remove records older than the rolling window."""
        cutoff = time.monotonic() - self._window_seconds
        while self._records and self._records[0].timestamp < cutoff:
            self._records.popleft()

    def _log_usage(self) -> None:
        usage = self.current_usage_percent()
        if usage > self._max_duty_percent * 0.8:
            logger.warning(
                "Duty cycle at %.2f%% (limit %.1f%%, region %s)",
                usage, self._max_duty_percent, self._region,
            )
