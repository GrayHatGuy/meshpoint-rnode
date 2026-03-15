from __future__ import annotations

import json

from fastapi import APIRouter

from src.analytics.signal_analyzer import SignalAnalyzer
from src.analytics.traffic_monitor import TrafficMonitor
from src.storage.packet_repository import PacketRepository

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

_signal_analyzer: SignalAnalyzer | None = None
_traffic_monitor: TrafficMonitor | None = None
_packet_repo: PacketRepository | None = None


def init_routes(
    signal_analyzer: SignalAnalyzer,
    traffic_monitor: TrafficMonitor,
    packet_repo: PacketRepository | None = None,
) -> None:
    global _signal_analyzer, _traffic_monitor, _packet_repo
    _signal_analyzer = signal_analyzer
    _traffic_monitor = traffic_monitor
    _packet_repo = packet_repo


@router.get("/traffic")
async def traffic_summary():
    return await _traffic_monitor.get_traffic_summary()


@router.get("/traffic/timeline")
async def traffic_timeline(minutes: int = 60, bucket_minutes: int = 5):
    return await _traffic_monitor.get_recent_activity(minutes, bucket_minutes)


@router.get("/signal/rssi")
async def rssi_distribution():
    return await _signal_analyzer.get_rssi_distribution()


@router.get("/signal/snr")
async def snr_distribution():
    return await _signal_analyzer.get_snr_distribution()


@router.get("/signal/summary")
async def signal_summary():
    return await _signal_analyzer.get_signal_summary()


@router.get("/topology")
async def network_topology():
    """Extract node-to-node links from NEIGHBORINFO packets."""
    if not _packet_repo:
        return []

    rows = await _packet_repo._db.fetch_all(
        """
        SELECT source_id, decoded_payload, rssi, snr, timestamp
        FROM packets
        WHERE packet_type = 'neighborinfo' AND decoded_payload IS NOT NULL
        ORDER BY timestamp DESC
        """,
    )

    seen_links: dict[str, dict] = {}
    for row in rows:
        source = row["source_id"]
        try:
            payload = json.loads(row["decoded_payload"])
        except (json.JSONDecodeError, TypeError):
            continue

        neighbors = payload.get("neighbors", [])
        if isinstance(neighbors, list):
            for neighbor in neighbors:
                nid = neighbor.get("node_id") or neighbor.get("id")
                if not nid:
                    continue
                nid = str(nid)
                link_key = f"{min(source, nid)}_{max(source, nid)}"
                if link_key not in seen_links:
                    seen_links[link_key] = {
                        "source": source,
                        "target": nid,
                        "rssi": row.get("rssi"),
                        "snr": row.get("snr"),
                        "last_seen": row["timestamp"],
                    }

    return list(seen_links.values())
