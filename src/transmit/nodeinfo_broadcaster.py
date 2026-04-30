"""Periodic Meshtastic NodeInfo broadcaster.

Announces the Meshpoint's identity (node_id, long_name, short_name) on
the mesh so receiving Meshtastic clients can build a stable contact
entry. Without this, recipients have no friendly name to attach to
direct messages from the Meshpoint and DMs may show as 'Sent' in the
dashboard but never arrive.

Identity is captured at construction time. Changes to long_name /
short_name in the dashboard radio tab take effect on the next service
restart, matching the existing UX contract for ``transmit.node_id``.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.transmit.tx_service import HW_MODEL_PORTDUINO, TxService

logger = logging.getLogger(__name__)

DEFAULT_STARTUP_DELAY_SECONDS = 60
DEFAULT_INTERVAL_SECONDS = 180 * 60

INTERVAL_DISABLED = 0
INTERVAL_MIN_MINUTES = 5
INTERVAL_MAX_MINUTES = 1440


def clamp_interval_minutes(value: int) -> int:
    """Clamp the interval to the supported range; log WARN if out of bounds.

    ``0`` is the documented disable sentinel and passes through unchanged.
    Negative values are also treated as disabled (with a WARN). Otherwise
    the value is clamped to ``5..1440`` since below 5 minutes is impolite
    on busy meshes and above 24 hours risks new clients in range not
    discovering the Meshpoint within a reasonable window.
    """
    if value == INTERVAL_DISABLED:
        return INTERVAL_DISABLED
    if value < 0:
        logger.warning(
            "transmit.nodeinfo.interval_minutes=%d is negative, "
            "treating as disabled (0).",
            value,
        )
        return INTERVAL_DISABLED
    if value < INTERVAL_MIN_MINUTES:
        logger.warning(
            "transmit.nodeinfo.interval_minutes=%d is below minimum %d, "
            "clamping. Below 5 minutes is impolite on busy meshes. "
            "Set to 0 to disable broadcasts entirely.",
            value, INTERVAL_MIN_MINUTES,
        )
        return INTERVAL_MIN_MINUTES
    if value > INTERVAL_MAX_MINUTES:
        logger.warning(
            "transmit.nodeinfo.interval_minutes=%d is above maximum %d, "
            "clamping. Above 24 hours risks new clients in range not "
            "discovering you.",
            value, INTERVAL_MAX_MINUTES,
        )
        return INTERVAL_MAX_MINUTES
    return value


class NodeInfoBroadcaster:
    """Schedules periodic NodeInfo broadcasts via :class:`TxService`."""

    def __init__(
        self,
        tx_service: TxService,
        long_name: str,
        short_name: str,
        *,
        startup_delay_seconds: int = DEFAULT_STARTUP_DELAY_SECONDS,
        interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
        hw_model: int = HW_MODEL_PORTDUINO,
    ):
        self._tx = tx_service
        self._long_name = long_name
        self._short_name = short_name
        self._startup_delay = startup_delay_seconds
        self._interval = interval_seconds
        self._hw_model = hw_model
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._started_at: Optional[datetime] = None
        self._last_sent_at: Optional[datetime] = None
        # Event-driven wake signal for hot-reload of the broadcast
        # interval. set() from sync or async context; the loop picks
        # up the new interval within milliseconds.
        self._interval_changed = asyncio.Event()

    @property
    def is_running(self) -> bool:
        return self._running and self._task is not None and not self._task.done()

    @property
    def interval_seconds(self) -> int:
        return self._interval

    @property
    def startup_delay_seconds(self) -> int:
        return self._startup_delay

    @property
    def last_sent_at(self) -> Optional[datetime]:
        return self._last_sent_at

    @property
    def next_due_at(self) -> Optional[datetime]:
        """Wall-clock time of the next scheduled broadcast.

        Before the first broadcast, this is start time + startup delay.
        After the first broadcast, it's last_sent_at + interval.
        Returns ``None`` if the broadcaster hasn't been started yet
        OR if the loop is paused (``interval == 0``); a paused loop
        has no scheduled next broadcast and the frontend countdown
        should render the paused state, not a stale timestamp.
        """
        if not self._running:
            return None
        if self._interval == 0:
            return None
        if self._last_sent_at is not None:
            return self._last_sent_at + timedelta(seconds=self._interval)
        if self._started_at is not None:
            return self._started_at + timedelta(seconds=self._startup_delay)
        return None

    async def start(self) -> None:
        """Schedule the broadcast loop. No-op if already running."""
        if self.is_running:
            logger.debug("NodeInfoBroadcaster already running")
            return
        self._running = True
        self._started_at = datetime.now(timezone.utc)
        self._task = asyncio.create_task(
            self._loop(), name="nodeinfo-broadcaster"
        )
        logger.info(
            "NodeInfo broadcaster scheduled: first TX in %ds, "
            "interval %ds, long=%r short=%r",
            self._startup_delay, self._interval,
            self._long_name, self._short_name,
        )

    async def stop(self, timeout: float = 5.0) -> None:
        """Cancel the broadcast loop and wait for it to finish."""
        self._running = False
        task = self._task
        if task is None:
            return
        task.cancel()
        try:
            await asyncio.wait_for(task, timeout=timeout)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        finally:
            self._task = None

    def set_interval(self, minutes: int) -> int:
        """Hot-reload the broadcast interval. Returns the clamped value.

        Mutates the running broadcast loop in place: the new interval
        takes effect within milliseconds of this call. Setting to ``0``
        pauses the loop (no new broadcasts) without stopping it;
        restoring to a non-zero value resumes immediately. The next
        broadcast fires at ``last_sent_at + new_interval`` (or right
        away if that's already in the past).

        Calls during the pre-first-broadcast window (startup delay
        still elapsing, or paused-since-boot with no broadcasts yet)
        re-anchor ``_started_at`` so the dashboard countdown reflects
        "broadcast imminent" instead of continuing to count toward
        the original startup deadline.

        Safe to call from any context (sync or async). The loop wakes
        via an :class:`asyncio.Event` so there's no busy polling.
        """
        clamped = clamp_interval_minutes(minutes)
        previous = self._interval
        self._interval = clamped * 60
        if previous != self._interval:
            logger.info(
                "NodeInfo interval hot-reloaded: %ds -> %ds",
                previous, self._interval,
            )
        if (
            self._interval > 0
            and self._last_sent_at is None
            and self._started_at is not None
        ):
            self._started_at = (
                datetime.now(timezone.utc)
                - timedelta(seconds=self._startup_delay)
            )
        self._interval_changed.set()
        return clamped

    def _is_due_now(self) -> bool:
        """True if the broadcast loop should fire now."""
        if self._interval == 0:
            return False
        if self._last_sent_at is None:
            return True
        next_due = self._last_sent_at + timedelta(seconds=self._interval)
        return datetime.now(timezone.utc) >= next_due

    def _sleep_until_next(self) -> float:
        """Seconds to sleep before the next scheduled broadcast.

        Returns ``0.0`` when the broadcast is already due or overdue
        so the loop can iterate without sleeping.
        """
        if self._interval == 0:
            return 0.0
        if self._last_sent_at is None:
            return float(self._interval)
        next_due = self._last_sent_at + timedelta(seconds=self._interval)
        remaining = (next_due - datetime.now(timezone.utc)).total_seconds()
        return max(0.0, remaining)

    async def _loop(self) -> None:
        try:
            if self._startup_delay > 0:
                self._interval_changed.clear()
                try:
                    await asyncio.wait_for(
                        self._interval_changed.wait(),
                        timeout=self._startup_delay,
                    )
                except asyncio.TimeoutError:
                    pass
            while self._running:
                if self._interval == 0:
                    self._interval_changed.clear()
                    await self._interval_changed.wait()
                    continue

                if self._is_due_now():
                    await self._broadcast_once()
                    if not self._running:
                        break

                self._interval_changed.clear()
                sleep_seconds = self._sleep_until_next()
                if sleep_seconds <= 0:
                    continue
                try:
                    await asyncio.wait_for(
                        self._interval_changed.wait(),
                        timeout=sleep_seconds,
                    )
                except asyncio.TimeoutError:
                    pass
        except asyncio.CancelledError:
            logger.debug("NodeInfo broadcaster cancelled")
            raise
        except Exception:
            logger.exception("NodeInfo broadcaster loop crashed")

    async def _broadcast_once(self):
        return await self.broadcast_now()

    async def broadcast_now(self):
        """Send a single NodeInfo broadcast right now.

        Public entry point used by the "Send Now" button on the radio
        tab and by the periodic loop. Updates ``last_sent_at`` on
        success so the dashboard countdown re-anchors. Returns the
        underlying :class:`SendResult` so callers can surface errors;
        never raises.
        """
        try:
            result = await self._tx.send_nodeinfo(
                long_name=self._long_name,
                short_name=self._short_name,
                hw_model=self._hw_model,
            )
        except Exception as exc:
            logger.exception("NodeInfo send raised")
            from src.transmit.tx_service import SendResult
            return SendResult(
                success=False, protocol="meshtastic", error=str(exc),
            )

        if result.success:
            self._last_sent_at = datetime.now(timezone.utc)
            logger.info(
                "NodeInfo broadcast OK: id=%s airtime=%dms",
                result.packet_id, result.airtime_ms,
            )
        else:
            logger.warning(
                "NodeInfo broadcast skipped: %s", result.error or "unknown"
            )
        return result
