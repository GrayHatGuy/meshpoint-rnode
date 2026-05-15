from __future__ import annotations

import logging
from typing import Optional

from src.decode.crypto_service import CryptoService
from src.decode.meshtastic_decoder import MeshtasticDecoder
from src.decode.meshcore_decoder import MeshcoreDecoder
from src.decode.rnode_decoder import RnodeDecoder
from src.models.packet import Packet, Protocol
from src.models.signal import SignalMetrics

logger = logging.getLogger(__name__)

MESHTASTIC_SYNC_WORD = 0x2B


class PacketRouter:
    """Routes raw captured bytes to the appropriate protocol decoder.

    Protocol detection strategy:
    - If the capture source provides protocol hint, use it directly
    - Otherwise attempt Meshtastic decode first (most common),
      then fall back to Meshcore
    """

    def __init__(self, crypto: CryptoService):
        self._meshtastic = MeshtasticDecoder(crypto)
        self._meshcore = MeshcoreDecoder(crypto)
        self._rnode = RnodeDecoder()

    @property
    def meshtastic_decoder(self) -> MeshtasticDecoder:
        return self._meshtastic

    @property
    def meshcore_decoder(self) -> MeshcoreDecoder:
        return self._meshcore

    @property
    def rnode_decoder(self) -> RnodeDecoder:
        return self._rnode

    def decode(
        self,
        raw_bytes: bytes,
        signal: Optional[SignalMetrics] = None,
        protocol_hint: Optional[Protocol] = None,
    ) -> Optional[Packet]:
        if protocol_hint == Protocol.MESHTASTIC:
            packet = self._meshtastic.decode(raw_bytes, signal)
            if packet:
                logger.info(
                    "Meshtastic packet (hint) type=%s src=%s decrypted=%s",
                    packet.packet_type.value, packet.source_id, packet.decrypted,
                )
            return packet

        if protocol_hint == Protocol.MESHCORE:
            packet = self._meshcore.decode(raw_bytes, signal)
            if packet:
                logger.info(
                    "Meshcore packet (hint) type=%s src=%s decrypted=%s",
                    packet.packet_type.value, packet.source_id, packet.decrypted,
                )
            return packet

        if protocol_hint == Protocol.RETICULUM:
            packet = self._rnode.decode(raw_bytes, signal=signal)
            if packet:
                logger.info(
                    "Reticulum packet (hint) type=%s dest=%s hops=%d",
                    packet.packet_type.value,
                    packet.destination_id,
                    packet.hop_limit,
                )
            return packet

        packet = self._meshtastic.decode(raw_bytes, signal)
        if packet and packet.decrypted:
            logger.info(
                "Decoded %s packet (type=%s, src=%s)",
                packet.protocol.value, packet.packet_type.value, packet.source_id,
            )
            return packet

        meshcore_packet = self._meshcore.decode(raw_bytes, signal)
        if meshcore_packet and meshcore_packet.decrypted:
            logger.info(
                "Decoded %s packet (type=%s, src=%s)",
                meshcore_packet.protocol.value,
                meshcore_packet.packet_type.value,
                meshcore_packet.source_id,
            )
            return meshcore_packet

        result = packet or meshcore_packet
        if result:
            logger.info(
                "Undecrypted packet classified as %s (src=%s, %d bytes)",
                result.protocol.value, result.source_id, len(raw_bytes),
            )
        return result
