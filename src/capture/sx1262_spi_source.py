"""Waveshare SX1262 SPI capture source for MeshCore RX.

Opens the SPI device and exposes a CaptureSource interface for the
capture coordinator. Continuous MeshCore RX support is parked while
hardware coexistence with the RAK Pi HAT is resolved (see ROADMAP.md).
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import AsyncIterator

from src.capture.base import CaptureSource
from src.models.packet import RawCapture

logger = logging.getLogger(__name__)


class Sx1262SpiCaptureSource(CaptureSource):
    """Captures MeshCore LoRa frames via Waveshare SX1262 HAT (SPI)."""

    def __init__(
        self,
        *,
        spi_device: str,
        gpio_cs_bcm: int,
        gpio_reset_bcm: int,
        gpio_busy_bcm: int,
        gpio_dio1_bcm: int,
        gpio_txen_bcm: int | None = None,
        busy_timeout_seconds: float = 5.0,
    ) -> None:
        self._spi_device = spi_device
        self._gpio_cs_bcm = gpio_cs_bcm
        self._gpio_reset_bcm = gpio_reset_bcm
        self._gpio_busy_bcm = gpio_busy_bcm
        self._gpio_dio1_bcm = gpio_dio1_bcm
        self._gpio_txen_bcm = gpio_txen_bcm
        self._busy_timeout = busy_timeout_seconds
        self._running = False
        self._spi: object = None

    @property
    def name(self) -> str:
        return "sx1262_spi"

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self) -> None:
        try:
            import spidev  # noqa: PLC0415
        except ImportError as exc:
            raise RuntimeError(
                "spidev is required for SX1262 SPI capture on Raspberry Pi."
            ) from exc

        bus, cs = _parse_spidev_path(self._spi_device)
        spi = spidev.SpiDev()
        spi.open(bus, cs)
        spi.max_speed_hz = 2_000_000
        spi.mode = 0
        spi.no_cs = True
        self._spi = spi
        self._running = True
        logger.info(
            "SX1262 SPI opened %s (bus=%s ce=%s no_cs=True); "
            "GPIO cs=%s reset=%s busy=%s dio1=%s txen=%s",
            self._spi_device,
            bus,
            cs,
            self._gpio_cs_bcm,
            self._gpio_reset_bcm,
            self._gpio_busy_bcm,
            self._gpio_dio1_bcm,
            self._gpio_txen_bcm,
        )

    async def stop(self) -> None:
        self._running = False
        if self._spi is not None:
            try:
                self._spi.close()
            except Exception:
                logger.debug("SPI close failed", exc_info=True)
            self._spi = None
        logger.info("SX1262 SPI capture stopped")

    async def packets(self) -> AsyncIterator[RawCapture]:
        while self._running:
            await asyncio.sleep(1.0)


def _parse_spidev_path(path: str) -> tuple[int, int]:
    match = re.match(r"^/dev/spidev(\d+)\.(\d+)$", path)
    if not match:
        raise ValueError(f"Invalid spidev path: {path}")
    return int(match.group(1)), int(match.group(2))
