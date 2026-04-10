"""MeshCore message transmission via USB or TCP companion.

Wraps the meshcore Python library for outbound messaging. Shares
the existing MeshCore connection from MeshcoreUsbCaptureSource
to avoid opening a second serial connection to the same port.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class SendResult:
    """Outcome of a MeshCore send attempt."""

    success: bool
    event_type: str = ""
    error: str = ""


@dataclass
class RadioStatus:
    """MeshCore companion radio parameters."""

    frequency_mhz: float = 0.0
    bandwidth_khz: float = 0.0
    spreading_factor: int = 0
    coding_rate: int = 0
    tx_power: int = 0
    name: str = ""


class MeshCoreTxClient:
    """Sends messages through a MeshCore companion node.

    Designed to share the MeshCore connection already held by
    MeshcoreUsbCaptureSource. Pass the existing instance via
    set_connection() rather than creating a new serial connection.
    """

    def __init__(self):
        self._mc = None
        self._connected = False
        self._post_command_callback = None

    @property
    def connected(self) -> bool:
        return self._connected and self._mc is not None

    def set_connection(self, mc_instance) -> None:
        """Attach an existing MeshCore connection from the capture source."""
        self._mc = mc_instance
        self._connected = mc_instance is not None
        if self._connected:
            logger.info("MeshCore TX client attached to shared connection")

    def set_post_command_callback(self, callback) -> None:
        """Register a coroutine to run after each command completes.

        Used to restart auto_message_fetching on the USB source after
        TX operations that may disrupt the event subscription loop.
        """
        self._post_command_callback = callback

    async def _run_post_command(self) -> None:
        if self._post_command_callback:
            try:
                await self._post_command_callback()
            except Exception:
                logger.debug("Post-command callback failed", exc_info=True)

    async def create_connection(
        self,
        port: str,
        baud_rate: int = 115200,
        connection_type: str = "serial",
        tcp_host: str = "",
        tcp_port: int = 0,
    ) -> bool:
        """Create a standalone connection (only if no shared one exists)."""
        if self._connected:
            return True
        try:
            from meshcore import MeshCore

            if connection_type == "tcp" and tcp_host:
                self._mc = await MeshCore.create_tcp(tcp_host, tcp_port)
            else:
                self._mc = await MeshCore.create_serial(port, baud_rate)
            self._connected = True
            logger.info("MeshCore TX client connected (%s)", connection_type)
            return True
        except Exception:
            logger.exception("MeshCore TX client connection failed")
            self._connected = False
            return False

    async def send_channel_message(
        self, channel: int, text: str
    ) -> SendResult:
        """Send a broadcast message on a MeshCore channel."""
        if not self.connected:
            return SendResult(success=False, error="Not connected")
        try:
            result = await asyncio.wait_for(
                self._mc.commands.send_chan_msg(channel, text),
                timeout=10.0,
            )
            event_type = (
                result.type.value
                if hasattr(result.type, "value")
                else str(result.type)
            )
            logger.info(
                "MeshCore channel %d message sent: %s", channel, event_type
            )
            await self._run_post_command()
            return SendResult(success=True, event_type=event_type)
        except asyncio.TimeoutError:
            await self._run_post_command()
            return SendResult(success=False, error="Send timed out")
        except Exception as exc:
            logger.exception("MeshCore channel send failed")
            await self._run_post_command()
            return SendResult(success=False, error=str(exc))

    async def send_direct_message(
        self, destination, text: str
    ) -> SendResult:
        """Send a direct message to a MeshCore contact."""
        if not self.connected:
            return SendResult(success=False, error="Not connected")
        try:
            result = await asyncio.wait_for(
                self._mc.commands.send_msg(destination, text),
                timeout=10.0,
            )
            event_type = (
                result.type.value
                if hasattr(result.type, "value")
                else str(result.type)
            )
            logger.info("MeshCore DM sent: %s", event_type)
            await self._run_post_command()
            return SendResult(success=True, event_type=event_type)
        except asyncio.TimeoutError:
            await self._run_post_command()
            return SendResult(success=False, error="Send timed out")
        except Exception as exc:
            logger.exception("MeshCore DM send failed")
            await self._run_post_command()
            return SendResult(success=False, error=str(exc))

    async def send_advert(self, flood: bool = False) -> SendResult:
        """Broadcast a node advertisement."""
        if not self.connected:
            return SendResult(success=False, error="Not connected")
        try:
            result = await asyncio.wait_for(
                self._mc.commands.send_advert(flood=flood),
                timeout=10.0,
            )
            event_type = (
                result.type.value
                if hasattr(result.type, "value")
                else str(result.type)
            )
            logger.info("MeshCore advert sent: %s", event_type)
            await self._run_post_command()
            return SendResult(success=True, event_type=event_type)
        except asyncio.TimeoutError:
            await self._run_post_command()
            return SendResult(success=False, error="Advert timed out")
        except Exception as exc:
            logger.exception("MeshCore advert send failed")
            await self._run_post_command()
            return SendResult(success=False, error=str(exc))

    @staticmethod
    def _normalize_contact_payload(payload) -> list[dict]:
        """Accept both dict-keyed-by-pubkey and list formats."""
        if isinstance(payload, dict):
            return list(payload.values())
        if isinstance(payload, list):
            return [e for e in payload if isinstance(e, dict)]
        return []

    async def get_radio_info(self) -> Optional[RadioStatus]:
        """Read companion radio parameters."""
        if not self.connected:
            return None
        try:
            info = await asyncio.wait_for(
                self._mc.commands.send_device_query(),
                timeout=10.0,
            )
            payload = info.payload if isinstance(info.payload, dict) else {}
            return RadioStatus(
                frequency_mhz=payload.get("radio_freq", 0.0),
                bandwidth_khz=payload.get("radio_bw", 0.0),
                spreading_factor=payload.get("radio_sf", 0),
                coding_rate=payload.get("radio_cr", 0),
                tx_power=payload.get("tx_power", 0),
                name=payload.get("name", ""),
            )
        except Exception:
            logger.exception("Failed to read MeshCore radio info")
            return None

    async def get_contacts(self) -> list[dict]:
        """Retrieve the companion's contact list."""
        if not self.connected:
            return []
        try:
            result = await asyncio.wait_for(
                self._mc.commands.get_contacts(),
                timeout=10.0,
            )
            entries = self._normalize_contact_payload(result.payload)
            contacts = []
            for i, entry in enumerate(entries):
                name = (
                    entry.get("adv_name")
                    or entry.get("name")
                    or ""
                )
                pk = entry.get("public_key", "")
                if name and pk:
                    contacts.append({
                        "index": i,
                        "name": name,
                        "public_key": pk,
                        "last_seen": entry.get("lastmod", 0),
                    })
            logger.info("get_contacts: %d contacts parsed", len(contacts))
            return contacts
        except Exception:
            logger.exception("Failed to retrieve MeshCore contacts")
            return []
