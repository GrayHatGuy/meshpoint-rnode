"""ctypes wrapper for the Semtech SX1302 HAL (libloragw).

Provides Python bindings to the C library functions needed for
concentrator-based packet capture and LoRa transmission via the
SX1261 companion radio. Only functional on a Raspberry Pi with
the patched libloragw.so compiled and installed.
"""

from __future__ import annotations

import ctypes
import logging
import os
from dataclasses import dataclass
from typing import Optional

from src.hal.concentrator_config import ConcentratorChannelPlan
from src.hal.sx1302_types import (
    LgwConfBoardS,
    LgwConfRxifS,
    LgwConfRxrfS,
    LgwPktRxS,
    LgwPktTxS,
    LgwTxGainLutS,
)

logger = logging.getLogger(__name__)

LGW_HAL_SUCCESS = 0
LGW_HAL_ERROR = -1
LGW_PKT_MAX = 16
LGW_IF_CHAIN_NB = 10
LGW_MULTI_NB = 8

LGW_COM_SPI = 0
LGW_RADIO_TYPE_SX1250 = 5

BW_125KHZ = 0x04
BW_250KHZ = 0x05
BW_500KHZ = 0x06
BW_MAP = {BW_125KHZ: 125.0, BW_250KHZ: 250.0, BW_500KHZ: 500.0}

BW_KHZ_TO_HAL = {125: BW_125KHZ, 250: BW_250KHZ, 500: BW_500KHZ}

STAT_CRC_OK = 0x10
STAT_CRC_BAD = 0x11
STAT_NO_CRC = 0x01

_STATUS_NAMES = {
    STAT_CRC_OK: "CRC_OK",
    STAT_CRC_BAD: "CRC_BAD",
    STAT_NO_CRC: "NO_CRC",
}

MOD_LORA = 0x10
TX_MODE_IMMEDIATE = 0
TX_STATUS = 1
TX_STATUS_FREE = 2
TX_STATUS_EMITTING = 4


@dataclass
class ConcentratorPacket:
    """Decoded packet from the concentrator hardware."""

    payload: bytes
    frequency_hz: int
    rssi: float
    snr: float
    spreading_factor: int
    bandwidth: int
    coderate: int
    crc_ok: bool
    timestamp_us: int
    if_chain: int = 0    # which demodulator captured this packet (0..7 = multi-SF, 8 = single-SF)


class SX1302Wrapper:
    """Python interface to the SX1302 concentrator via libloragw.

    Usage:
        wrapper = SX1302Wrapper(spi_path="/dev/spidev0.0")
        wrapper.load()
        wrapper.configure(channel_plan)
        wrapper.set_syncword(0x2B)
        wrapper.start()
        packets = wrapper.receive()
        wrapper.stop()
    """

    def __init__(
        self,
        lib_path: Optional[str] = None,
        spi_path: str = "/dev/spidev0.0",
    ):
        self._lib: Optional[ctypes.CDLL] = None
        self._lib_path = lib_path or self._find_library()
        self._spi_path = spi_path
        self._started = False
        self._debug_rx = os.getenv("MESHPOINT_DEBUG_RX") == "1"
        self._crc_bad_count = 0

    def load(self) -> None:
        if not self._lib_path or not os.path.exists(self._lib_path):
            raise FileNotFoundError(
                f"libloragw not found at {self._lib_path}. "
                "Build the patched SX1302 HAL first."
            )
        self._lib = ctypes.CDLL(self._lib_path)
        self._setup_function_signatures()
        logger.info("Loaded libloragw from %s", self._lib_path)

    def reset(self, gpio_pins: list[int] | None = None) -> None:
        """Toggle the concentrator reset pins (required before lgw_start).

        Different carrier boards route SX1302 reset to different GPIOs
        (pin 17 or 25). Both are toggled by default since asserting
        reset on an unconnected pin is harmless.
        Delegated to systemd ExecStartPre for root access;
        this method is a best-effort fallback via pinctrl subprocess.
        """
        import subprocess
        import time

        if gpio_pins is None:
            gpio_pins = [17, 25]

        try:
            for pin in gpio_pins:
                subprocess.run(
                    ["pinctrl", "set", str(pin), "op", "dh"],
                    check=True, capture_output=True,
                )
            time.sleep(0.1)
            for pin in gpio_pins:
                subprocess.run(
                    ["pinctrl", "set", str(pin), "op", "dl"],
                    check=True, capture_output=True,
                )
            time.sleep(0.1)
            logger.info("Concentrator reset via pinctrl GPIO %s", gpio_pins)
        except (OSError, subprocess.CalledProcessError):
            logger.warning(
                "In-app GPIO reset failed (pins %s) -- relying on systemd ExecStartPre",
                gpio_pins,
            )

    def configure(self, plan: ConcentratorChannelPlan) -> None:
        """Apply board, RF, and IF channel configuration before start."""
        if self._lib is None:
            self.load()

        self._configure_board()
        self._configure_rf_chains(plan)
        self._configure_if_channels(plan)
        logger.info("Concentrator configured with %d IF channels",
                     len(plan.multi_sf_channels) + (1 if plan.single_sf_channel else 0))

    def start(self) -> None:
        if self._lib is None:
            self.load()
        result = self._lib.lgw_start()
        if result != LGW_HAL_SUCCESS:
            raise RuntimeError("lgw_start() failed")
        self._started = True
        logger.info("SX1302 concentrator started")

    def stop(self) -> None:
        if self._started and self._lib:
            self._lib.lgw_stop()
            self._started = False
            logger.info("SX1302 concentrator stopped")

    def receive(self) -> list[ConcentratorPacket]:
        """Poll for received packets. Non-blocking.

        lgw_receive returns the number of packets fetched (>= 0)
        or LGW_HAL_ERROR (-1) on failure. There is no third out-parameter.
        """
        if not self._started:
            return []

        pkt_array = (LgwPktRxS * LGW_PKT_MAX)()

        count = self._lib.lgw_receive(LGW_PKT_MAX, pkt_array)

        if count < 0:
            logger.warning("lgw_receive returned error (%d)", count)
            return []

        if count > 0:
            logger.info("lgw_receive returned %d packet(s)", count)

        packets = []
        for i in range(count):
            pkt = pkt_array[i]
            if pkt.size == 0:
                continue

            if pkt.status == STAT_CRC_BAD:
                self._crc_bad_count += 1
                logger.warning(
                    "RX CRC_BAD if=%d sf%d bw=%g rssi=%.1f snr=%.1f size=%d "
                    "(total CRC_BAD: %d)",
                    pkt.if_chain, pkt.datarate,
                    BW_MAP.get(pkt.bandwidth, pkt.bandwidth),
                    pkt.rssic, pkt.snr, pkt.size, self._crc_bad_count,
                )
                continue
            elif self._debug_rx:
                status_name = _STATUS_NAMES.get(
                    pkt.status, f"0x{pkt.status:02X}"
                )
                logger.info(
                    "RX if=%d sf%d bw=%g status=%s rssi=%.1f snr=%.1f size=%d",
                    pkt.if_chain, pkt.datarate,
                    BW_MAP.get(pkt.bandwidth, pkt.bandwidth),
                    status_name, pkt.rssic, pkt.snr, pkt.size,
                )

            packets.append(
                ConcentratorPacket(
                    payload=bytes(pkt.payload[: pkt.size]),
                    frequency_hz=pkt.freq_hz,
                    rssi=pkt.rssic,
                    snr=pkt.snr,
                    spreading_factor=pkt.datarate,
                    bandwidth=pkt.bandwidth,
                    coderate=pkt.coderate,
                    crc_ok=(pkt.status == STAT_CRC_OK),
                    timestamp_us=pkt.count_us,
                    if_chain=pkt.if_chain,
                )
            )

        return packets

    @property
    def crc_bad_count(self) -> int:
        """Total CRC_BAD packets seen since process start.

        CRC failures are typically caused by overlapping LoRa transmissions
        on the same demodulator (capture effect failure) or weak signals.
        """
        return self._crc_bad_count

    def set_syncword(self, syncword: int) -> None:
        """Configure custom sync word (requires patched HAL).

        Applies one sync word to ALL demods (multi-SF + single-SF).
        For independent multi-SF / single-SF sync words use
        :meth:`set_syncword_pair` instead (requires Step 2 HAL patch).
        """
        if self._lib is None:
            self.load()
        result = self._lib.sx1302_lora_syncword(False, syncword)
        if result != LGW_HAL_SUCCESS:
            logger.warning("Failed to set sync word 0x%02X", syncword)
        else:
            logger.info("Sync word set to 0x%02X", syncword)

    def set_syncword_pair(
        self, multi_sf_syncword: int, single_sf_syncword: int,
    ) -> bool:
        """Configure independent sync words for multi-SF and single-SF demods.

        Requires the Step 2 HAL patch (``sx1302_lora_syncword_pair``).
        Returns True on success, False if the symbol is missing (older
        HAL build) so the caller can fall back to :meth:`set_syncword`.

        Single SX1302 hardware supports at most 2 distinct sync words:
        one for the multi-SF demod group, one for the single-SF demod.
        """
        if self._lib is None:
            self.load()
        if not hasattr(self._lib, "sx1302_lora_syncword_pair"):
            logger.warning(
                "set_syncword_pair: HAL symbol missing -- rebuild "
                "libloragw with patch_hal.sh to enable Step 2"
            )
            return False
        result = self._lib.sx1302_lora_syncword_pair(
            multi_sf_syncword, single_sf_syncword,
        )
        if result != LGW_HAL_SUCCESS:
            logger.warning(
                "Failed to set sync word pair multi=0x%02X single=0x%02X",
                multi_sf_syncword, single_sf_syncword,
            )
            return False
        logger.info(
            "Sync word pair set: multi-SF=0x%02X  single-SF=0x%02X",
            multi_sf_syncword, single_sf_syncword,
        )
        return True

    def set_tx_syncword(self, syncword: int) -> bool:
        """Override the sync word for the next TX packet.

        Updates the sx1302_tx_sw_peak1/2 globals that the patched TX
        path reads from. Call immediately before :meth:`send` if the
        outbound packet's protocol uses a different sync word than
        whatever the radio is configured for at RX time.

        Requires the Step 2 HAL patch. Returns True on success,
        False if the symbol is missing.
        """
        if self._lib is None:
            self.load()
        if not hasattr(self._lib, "sx1302_set_tx_syncword"):
            logger.warning(
                "set_tx_syncword: HAL symbol missing -- rebuild "
                "libloragw with patch_hal.sh to enable Step 2"
            )
            return False
        result = self._lib.sx1302_set_tx_syncword(syncword)
        if result != LGW_HAL_SUCCESS:
            logger.warning("Failed to override TX sync word 0x%02X", syncword)
            return False
        logger.debug("Next TX sync word set to 0x%02X", syncword)
        return True

    # ── TX operations ───────────────────────────────────────────────

    def configure_tx_gain(
        self, rf_chain: int, lut_entries: list[dict]
    ) -> None:
        """Configure the TX gain look-up table (call before start).

        Each entry: {"rf_power": int, "pa_gain": int, "pwr_idx": int}
        """
        if self._lib is None:
            self.load()

        lut = LgwTxGainLutS()
        lut.size = min(len(lut_entries), 16)
        for i, entry in enumerate(lut_entries[: lut.size]):
            lut.lut[i].rf_power = entry["rf_power"]
            lut.lut[i].pa_gain = entry.get("pa_gain", 0)
            lut.lut[i].pwr_idx = entry.get("pwr_idx", 0)
            lut.lut[i].dig_gain = entry.get("dig_gain", 0)
            lut.lut[i].dac_gain = entry.get("dac_gain", 3)
            lut.lut[i].mix_gain = entry.get("mix_gain", 5)

        result = self._lib.lgw_txgain_setconf(rf_chain, ctypes.byref(lut))
        if result != LGW_HAL_SUCCESS:
            raise RuntimeError(
                f"lgw_txgain_setconf(rf_chain={rf_chain}) failed"
            )
        logger.info(
            "TX gain LUT configured: %d entries on RF chain %d",
            lut.size, rf_chain,
        )

    def send(self, tx_pkt: LgwPktTxS, sync_word: Optional[int] = None) -> int:
        """Schedule a packet for transmission via lgw_send.

        When ``sync_word`` is provided the per-packet TX sync override is
        applied immediately before lgw_send so the outbound frame uses
        that protocol's sync word (e.g. 0x2B for Meshtastic, 0x42 for
        Reticulum). Required in Config A multi-protocol mode where the
        global TX sync default would otherwise be wrong for at least one
        protocol. Requires Step 2 HAL patch; silently no-ops on un-patched
        builds (TX still proceeds with whatever sync was last set).

        Returns LGW_HAL_SUCCESS (0) on success, negative on error.
        """
        if not self._started:
            raise RuntimeError("Concentrator not started, cannot transmit")

        if sync_word is not None:
            self.set_tx_syncword(sync_word)

        result = self._lib.lgw_send(ctypes.byref(tx_pkt))
        if result != LGW_HAL_SUCCESS:
            logger.error("lgw_send failed (code %d)", result)
        else:
            sync_tag = (
                f"  sync=0x{sync_word:02X}" if sync_word is not None else ""
            )
            logger.info(
                "TX queued: %d Hz, SF%d, %d bytes%s",
                tx_pkt.freq_hz, tx_pkt.datarate, tx_pkt.size, sync_tag,
            )
        return result

    def get_tx_status(self, rf_chain: int = 0) -> int:
        """Check TX status: TX_STATUS_FREE=2, TX_STATUS_EMITTING=4."""
        if self._lib is None:
            raise RuntimeError("Library not loaded")

        status = ctypes.c_uint8(0)
        self._lib.lgw_status(rf_chain, TX_STATUS, ctypes.byref(status))
        return status.value

    def abort_tx(self, rf_chain: int = 0) -> int:
        """Cancel a scheduled transmission."""
        if self._lib is None:
            raise RuntimeError("Library not loaded")
        return self._lib.lgw_abort_tx(rf_chain)

    def get_time_on_air(self, tx_pkt: LgwPktTxS) -> int:
        """Compute airtime in milliseconds for a TX packet."""
        if self._lib is None:
            raise RuntimeError("Library not loaded")
        return self._lib.lgw_time_on_air(ctypes.byref(tx_pkt))

    # ── Private: HAL configuration ──────────────────────────────────

    def _configure_board(self) -> None:
        conf = LgwConfBoardS()
        conf.lorawan_public = False
        conf.clksrc = 0
        conf.full_duplex = False
        conf.com_type = LGW_COM_SPI
        conf.com_path = self._spi_path.encode("ascii")

        result = self._lib.lgw_board_setconf(ctypes.byref(conf))
        if result != LGW_HAL_SUCCESS:
            raise RuntimeError("lgw_board_setconf() failed")
        logger.debug("Board configured (SPI=%s)", self._spi_path)

    def _configure_rf_chains(self, plan: ConcentratorChannelPlan) -> None:
        for rf_chain, freq_hz in enumerate([
            plan.radio_0_freq_hz,
            plan.radio_1_freq_hz,
        ]):
            conf = LgwConfRxrfS()
            conf.enable = True
            conf.freq_hz = freq_hz
            conf.rssi_offset = -215.4
            conf.type = LGW_RADIO_TYPE_SX1250
            conf.tx_enable = (rf_chain == 0)
            conf.single_input_mode = False

            result = self._lib.lgw_rxrf_setconf(rf_chain, ctypes.byref(conf))
            if result != LGW_HAL_SUCCESS:
                raise RuntimeError(f"lgw_rxrf_setconf({rf_chain}) failed")
            logger.debug("RF chain %d: %d Hz", rf_chain, freq_hz)

    def _configure_if_channels(self, plan: ConcentratorChannelPlan) -> None:
        radio_0_freq = plan.radio_0_freq_hz

        for i, ch in enumerate(plan.multi_sf_channels[:LGW_MULTI_NB]):
            conf = LgwConfRxifS()
            conf.enable = ch.enabled
            conf.rf_chain = 0 if ch.frequency_hz <= radio_0_freq + 500_000 else 1
            center = radio_0_freq if conf.rf_chain == 0 else plan.radio_1_freq_hz
            conf.freq_hz = ch.frequency_hz - center

            result = self._lib.lgw_rxif_setconf(i, ctypes.byref(conf))
            if result != LGW_HAL_SUCCESS:
                raise RuntimeError(f"lgw_rxif_setconf({i}) failed")

        if plan.single_sf_channel:
            ch = plan.single_sf_channel
            conf = LgwConfRxifS()
            conf.enable = ch.enabled
            conf.rf_chain = 0
            conf.freq_hz = ch.frequency_hz - radio_0_freq
            conf.bandwidth = BW_KHZ_TO_HAL.get(ch.bandwidth_khz, BW_250KHZ)
            conf.datarate = ch.spreading_factor

            result = self._lib.lgw_rxif_setconf(LGW_MULTI_NB, ctypes.byref(conf))
            if result != LGW_HAL_SUCCESS:
                raise RuntimeError(f"lgw_rxif_setconf({LGW_MULTI_NB}) failed")

    # ── Private: function signatures ────────────────────────────────

    def _setup_function_signatures(self) -> None:
        lib = self._lib

        lib.lgw_board_setconf.restype = ctypes.c_int
        lib.lgw_board_setconf.argtypes = [ctypes.POINTER(LgwConfBoardS)]

        lib.lgw_rxrf_setconf.restype = ctypes.c_int
        lib.lgw_rxrf_setconf.argtypes = [
            ctypes.c_uint8,
            ctypes.POINTER(LgwConfRxrfS),
        ]

        lib.lgw_rxif_setconf.restype = ctypes.c_int
        lib.lgw_rxif_setconf.argtypes = [
            ctypes.c_uint8,
            ctypes.POINTER(LgwConfRxifS),
        ]

        lib.lgw_start.restype = ctypes.c_int
        lib.lgw_start.argtypes = []

        lib.lgw_stop.restype = ctypes.c_int
        lib.lgw_stop.argtypes = []

        lib.lgw_receive.restype = ctypes.c_int
        lib.lgw_receive.argtypes = [
            ctypes.c_uint8,
            ctypes.POINTER(LgwPktRxS),
        ]

        lib.sx1302_lora_syncword.restype = ctypes.c_int
        lib.sx1302_lora_syncword.argtypes = [
            ctypes.c_bool,
            ctypes.c_uint8,
        ]

        # Step 2 patch symbols -- bind only if present so older HAL
        # builds without the patch still load cleanly.
        if hasattr(lib, "sx1302_lora_syncword_pair"):
            lib.sx1302_lora_syncword_pair.restype = ctypes.c_int
            lib.sx1302_lora_syncword_pair.argtypes = [
                ctypes.c_uint8,
                ctypes.c_uint8,
            ]
        if hasattr(lib, "sx1302_set_tx_syncword"):
            lib.sx1302_set_tx_syncword.restype = ctypes.c_int
            lib.sx1302_set_tx_syncword.argtypes = [ctypes.c_uint8]

        lib.lgw_txgain_setconf.restype = ctypes.c_int
        lib.lgw_txgain_setconf.argtypes = [
            ctypes.c_uint8,
            ctypes.POINTER(LgwTxGainLutS),
        ]

        lib.lgw_send.restype = ctypes.c_int
        lib.lgw_send.argtypes = [ctypes.POINTER(LgwPktTxS)]

        lib.lgw_status.restype = ctypes.c_int
        lib.lgw_status.argtypes = [
            ctypes.c_uint8,
            ctypes.c_uint8,
            ctypes.POINTER(ctypes.c_uint8),
        ]

        lib.lgw_abort_tx.restype = ctypes.c_int
        lib.lgw_abort_tx.argtypes = [ctypes.c_uint8]

        lib.lgw_time_on_air.restype = ctypes.c_uint32
        lib.lgw_time_on_air.argtypes = [ctypes.POINTER(LgwPktTxS)]

    @staticmethod
    def _find_library() -> str:
        candidates = [
            "/usr/local/lib/libloragw.so",
            "/usr/lib/libloragw.so",
            "./libloragw.so",
            "../sx1302_hal/libloragw/libloragw.so",
        ]
        for path in candidates:
            if os.path.exists(path):
                return path
        return candidates[0]
