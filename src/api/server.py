from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from src.analytics.network_mapper import NetworkMapper
from src.analytics.signal_analyzer import SignalAnalyzer
from src.analytics.traffic_monitor import TrafficMonitor
from src.api.routes import analytics, config_routes, device, messages, nodes, packets, system_metrics, telemetry, update_check
from src.api.upstream_client import UpstreamClient
from src.api.websocket_manager import WebSocketManager
from src.config import AppConfig, load_config, validate_activation
from src.coordinator import PipelineCoordinator
from src.log_format import print_banner, print_packet, setup_logging
from src.models.device_identity import DeviceIdentity, _stable_device_id
from src.models.packet import Packet
from src.storage.message_repository import MessageRepository
from src.transmit.tx_service import TxService

setup_logging()
logger = logging.getLogger(__name__)

ws_manager = WebSocketManager()
pipeline: PipelineCoordinator | None = None
upstream: UpstreamClient | None = None


def create_app(config: AppConfig | None = None) -> FastAPI:
    if config is None:
        config = load_config()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        global pipeline, upstream
        validate_activation(config)
        identity = DeviceIdentity(
            device_id=_stable_device_id(config.device.device_id),
            device_name=config.device.device_name,
            latitude=config.device.latitude,
            longitude=config.device.longitude,
            altitude=config.device.altitude,
            hardware_description=config.device.hardware_description,
            firmware_version=config.device.firmware_version,
        )
        pipeline = _build_pipeline(config)
        pipeline.on_packet(_on_packet_received)
        pipeline.on_packet(lambda pkt: print_packet(pkt))

        if config.transmit.enabled:
            _inject_tx_gain_into_source(pipeline)

        await pipeline.start()

        message_repo = MessageRepository(pipeline.database)
        tx_service = _build_tx_service(config, pipeline)
        mc_source = _find_meshcore_source(pipeline)
        meshcore_tx_ref = None
        if tx_service and hasattr(tx_service, '_meshcore_tx'):
            meshcore_tx_ref = tx_service._meshcore_tx
            if meshcore_tx_ref and meshcore_tx_ref.connected:
                import asyncio
                asyncio.get_running_loop().create_task(
                    _send_meshcore_advert(meshcore_tx_ref, mc_source)
                )
        _setup_message_interception(
            pipeline, message_repo, config, meshcore_tx_ref
        )

        upstream = UpstreamClient(config.upstream, identity)
        pipeline.on_packet(upstream.send_packet)
        await upstream.start()

        _init_routes(pipeline, config, identity, tx_service, message_repo)
        print_banner(config)
        logger.info("Mesh Point started -- listening for packets")
        yield
        await upstream.stop()
        await pipeline.stop()
        logger.info("Mesh Point stopped")

    app = FastAPI(
        title="Mesh Radar - Mesh Point",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.include_router(nodes.router)
    app.include_router(packets.router)
    app.include_router(analytics.router)
    app.include_router(device.router)
    app.include_router(system_metrics.router)
    app.include_router(telemetry.router)
    app.include_router(update_check.router)
    app.include_router(messages.router)
    app.include_router(config_routes.router)

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await ws_manager.connect(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            await ws_manager.disconnect(websocket)

    static_dir = Path(config.dashboard.static_dir)
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True))

    return app


def _build_pipeline(config: AppConfig) -> PipelineCoordinator:
    coordinator = PipelineCoordinator(config)

    for source_name in config.capture.sources:
        if source_name == "serial":
            _add_serial_source(coordinator, config)
        elif source_name == "concentrator":
            _add_concentrator_source(coordinator, config)
        elif source_name == "meshcore_usb":
            _add_meshcore_usb_source(coordinator, config)

    if (
        "meshcore_usb" not in config.capture.sources
        and config.capture.meshcore_usb.auto_detect
    ):
        _add_meshcore_usb_source(coordinator, config)

    return coordinator


def _add_serial_source(coordinator: PipelineCoordinator, config: AppConfig):
    try:
        from src.capture.serial_source import SerialCaptureSource
        coordinator.capture_coordinator.add_source(
            SerialCaptureSource(
                port=config.capture.serial_port,
                baud=config.capture.serial_baud,
            )
        )
    except ImportError:
        logger.warning("Serial capture unavailable")


def _add_concentrator_source(
    coordinator: PipelineCoordinator, config: AppConfig
):
    try:
        from src.capture.concentrator_source import ConcentratorCaptureSource
        coordinator.capture_coordinator.add_source(
            ConcentratorCaptureSource(
                spi_path=config.capture.concentrator_spi_device,
                syncword=config.radio.sync_word,
                radio_config=config.radio,
            )
        )
    except Exception:
        logger.exception("Concentrator source unavailable")


def _add_meshcore_usb_source(
    coordinator: PipelineCoordinator, config: AppConfig
):
    try:
        from src.capture.meshcore_usb_source import MeshcoreUsbCaptureSource
        usb_cfg = config.capture.meshcore_usb
        coordinator.capture_coordinator.add_source(
            MeshcoreUsbCaptureSource(
                serial_port=usb_cfg.serial_port,
                baud_rate=usb_cfg.baud_rate,
                auto_detect=usb_cfg.auto_detect,
            )
        )
    except ImportError:
        logger.warning(
            "MeshCore USB unavailable -- meshcore package not installed"
        )


def _build_tx_service(
    config: AppConfig, coord: PipelineCoordinator
) -> TxService | None:
    """Build the TX service if transmit is enabled in config."""
    if not config.transmit.enabled:
        logger.info("Transmit disabled in config")
        return None

    from src.transmit.duty_cycle import DutyCycleTracker
    from src.transmit.meshcore_tx_client import MeshCoreTxClient

    duty = DutyCycleTracker(
        region=config.radio.region,
        max_duty_percent=config.transmit.max_duty_cycle_percent,
    )
    meshcore_tx = MeshCoreTxClient()
    mc_source = _find_meshcore_source(coord)
    if mc_source and mc_source._meshcore:
        meshcore_tx.set_connection(mc_source._meshcore)
        meshcore_tx.set_post_command_callback(mc_source.restart_auto_fetching)

    wrapper = _get_concentrator_wrapper(coord)
    crypto = coord._crypto if hasattr(coord, "_crypto") else None
    channel_plan = _get_channel_plan(config)

    tx_svc = TxService(
        wrapper=wrapper,
        crypto=crypto,
        channel_plan=channel_plan,
        transmit_config=config.transmit,
        meshcore_tx=meshcore_tx,
        duty_tracker=duty,
        radio_config=config.radio,
    )
    logger.info(
        "Transmit service ready: MT=%s MC=%s",
        tx_svc.meshtastic_enabled, tx_svc.meshcore_enabled,
    )
    return tx_svc


RAK2287_TX_GAIN_LUT = [
    {"rf_power": 12, "pa_gain": 0, "pwr_idx": 15},
    {"rf_power": 13, "pa_gain": 0, "pwr_idx": 16},
    {"rf_power": 14, "pa_gain": 0, "pwr_idx": 17},
    {"rf_power": 15, "pa_gain": 0, "pwr_idx": 19},
    {"rf_power": 16, "pa_gain": 0, "pwr_idx": 20},
    {"rf_power": 17, "pa_gain": 0, "pwr_idx": 22},
    {"rf_power": 18, "pa_gain": 1, "pwr_idx": 1},
    {"rf_power": 19, "pa_gain": 1, "pwr_idx": 2},
    {"rf_power": 20, "pa_gain": 1, "pwr_idx": 3},
    {"rf_power": 21, "pa_gain": 1, "pwr_idx": 4},
    {"rf_power": 22, "pa_gain": 1, "pwr_idx": 5},
    {"rf_power": 23, "pa_gain": 1, "pwr_idx": 6},
    {"rf_power": 24, "pa_gain": 1, "pwr_idx": 7},
    {"rf_power": 25, "pa_gain": 1, "pwr_idx": 9},
    {"rf_power": 26, "pa_gain": 1, "pwr_idx": 11},
    {"rf_power": 27, "pa_gain": 1, "pwr_idx": 14},
]


def _inject_tx_gain_into_source(coord: PipelineCoordinator) -> None:
    """Patch the concentrator source startup to include TX gain config.

    lgw_txgain_setconf must be called between lgw_configure and lgw_start.
    Rather than stopping/restarting the concentrator after the capture loop
    is running (which kills RX), we patch the source's start() method to
    inject the TX gain LUT into its normal startup sequence.
    """
    conc_source = _find_concentrator_source(coord)
    if conc_source is None:
        return

    async def _start_with_tx_gain() -> None:
        conc_source._wrapper.load()
        conc_source._wrapper.reset()
        conc_source._wrapper.configure(conc_source._channel_plan)
        conc_source._wrapper.configure_tx_gain(0, RAK2287_TX_GAIN_LUT)
        logger.info(
            "TX gain LUT configured: %d entries on RF chain 0",
            len(RAK2287_TX_GAIN_LUT),
        )
        conc_source._wrapper.start()
        conc_source._wrapper.set_syncword(conc_source._syncword)
        conc_source._running = True
        logger.info(
            "Concentrator started with TX gain (syncword=0x%02X)",
            conc_source._syncword,
        )

    conc_source.start = _start_with_tx_gain


def _find_meshcore_source(coord: PipelineCoordinator):
    """Find the MeshCore USB capture source if it exists."""
    for src in coord.capture_coordinator._sources:
        if src.name == "meshcore_usb":
            return src
    return None


def _find_concentrator_source(coord: PipelineCoordinator):
    """Find the concentrator capture source."""
    for src in coord.capture_coordinator._sources:
        if hasattr(src, "_wrapper"):
            return src
    return None


def _get_concentrator_wrapper(coord: PipelineCoordinator):
    """Get the SX1302 wrapper from the concentrator source if running."""
    src = _find_concentrator_source(coord)
    return src._wrapper if src else None


def _get_channel_plan(config: AppConfig):
    """Build a channel plan for TX frequency/modulation parameters."""
    try:
        from src.hal.concentrator_config import ConcentratorChannelPlan
        return ConcentratorChannelPlan.for_region(config.radio.region)
    except Exception:
        return None


async def _send_meshcore_advert(meshcore_tx, mc_source=None) -> None:
    """Broadcast a name advertisement so other MeshCore nodes see a friendly name."""
    try:
        result = await meshcore_tx.send_advert()
        if result.success:
            logger.info("MeshCore advert sent on startup")
        else:
            logger.warning("MeshCore advert failed: %s", result.error)
    except Exception:
        logger.debug("MeshCore advert failed", exc_info=True)
    try:
        contacts = await meshcore_tx.get_contacts()
        logger.info("MeshCore contacts: %d peers", len(contacts))
        for c in contacts:
            pk = c.get("public_key", "")
            name = c.get("name", "")
            if pk and name:
                logger.info("  %s  %s", pk[:12], name)
    except Exception:
        logger.debug("Startup contact fetch failed", exc_info=True)
    if mc_source:
        await mc_source.restart_auto_fetching()


def _setup_message_interception(
    coord: PipelineCoordinator,
    message_repo: MessageRepository,
    config: AppConfig,
    meshcore_tx=None,
) -> None:
    """Register a callback to intercept TEXT messages for storage.

    Filters DMs: only saves messages involving our node_id as normal
    conversations. DMs between other nodes are tagged as 'overheard'.
    MeshCore DMs use destination_id='self' to indicate they're for us.
    """
    from src.models.packet import PacketType, Protocol

    our_node_id = config.transmit.node_id
    our_node_hex = f"{our_node_id:08x}" if our_node_id else ""

    mc_contact_cache: dict[str, str] = {}

    async def _refresh_mc_contacts() -> None:
        if not meshcore_tx or not meshcore_tx.connected:
            logger.debug("MC contact refresh skipped: not connected")
            return
        try:
            contacts = await meshcore_tx.get_contacts()
            for c in contacts:
                pk = c.get("public_key", "")
                name = c.get("name", "")
                if pk and name:
                    for prefix_len in (8, 12, 16, len(pk)):
                        mc_contact_cache[pk[:prefix_len].lower()] = name
            logger.debug("MC contact cache refreshed: %d entries", len(mc_contact_cache))
        except Exception:
            logger.debug("MC contact cache refresh failed", exc_info=True)

    def _resolve_mc_node_id(source: str, payload: dict) -> tuple[str, str]:
        """Resolve a MeshCore source to (node_id, display_name)."""
        src_lower = source.lower()
        for length in (len(src_lower), 12, 8, 16):
            cached = mc_contact_cache.get(src_lower[:length], "")
            if cached:
                return f"mc:{cached}", cached
        name = payload.get("long_name", "")
        if name:
            return f"mc:{name}", name
        return source, ""

    def on_text_packet(packet: Packet) -> None:
        if packet.packet_type != PacketType.TEXT:
            return
        text = ""
        if packet.decoded_payload:
            text = packet.decoded_payload.get("text", "")
        if not text:
            return

        dest = (packet.destination_id or "").lower()
        source = (packet.source_id or "").lower()
        is_broadcast = dest in ("ffffffff", "ffff", "broadcast") or dest.startswith("channel:")
        is_for_us = (
            (our_node_hex and dest == our_node_hex)
            or dest == "self"
        )

        if is_broadcast:
            if our_node_hex and source == our_node_hex:
                return
            node_id = f"broadcast:{packet.protocol.value}:0"
            direction = "received"
        elif is_for_us:
            node_id = packet.source_id or "unknown"
            direction = "received"
        elif our_node_hex and source == our_node_hex:
            node_id = packet.destination_id or "unknown"
            direction = "sent"
        else:
            node_id = packet.source_id or "unknown"
            direction = "overheard"

        node_name = ""
        if packet.decoded_payload:
            node_name = packet.decoded_payload.get("long_name", "")

        is_mc_dm = (
            packet.protocol == Protocol.MESHCORE
            and direction == "received"
            and not is_broadcast
        )

        rssi = packet.signal.rssi if packet.signal else None
        snr = packet.signal.snr if packet.signal else None

        import asyncio

        async def _save_and_notify() -> None:
            nonlocal node_id, node_name
            if is_mc_dm:
                if meshcore_tx:
                    await _refresh_mc_contacts()
                node_id, resolved_name = _resolve_mc_node_id(
                    node_id, packet.decoded_payload or {}
                )
                if resolved_name and not node_name:
                    node_name = resolved_name
            if is_broadcast and packet.protocol == Protocol.MESHCORE:
                node_name = (packet.decoded_payload or {}).get("long_name", "")
            row_id, is_dup = await message_repo.save_received(
                text=text,
                node_id=node_id,
                node_name=node_name,
                protocol=packet.protocol.value,
                packet_id=packet.packet_id or "",
                direction=direction,
                rssi=rssi,
                snr=snr,
            )
            if is_dup:
                row = await message_repo._db.fetch_one(
                    "SELECT rx_count, rssi, snr FROM messages WHERE id=?",
                    (row_id,),
                )
                await ws_manager.broadcast("message_updated", {
                    "packet_id": packet.packet_id or "",
                    "node_id": node_id,
                    "rx_count": row["rx_count"] if row else 2,
                    "rssi": round(row["rssi"], 1) if row and row["rssi"] else None,
                    "snr": round(row["snr"], 1) if row and row["snr"] else None,
                })
            else:
                ws_payload = {
                    "text": text,
                    "node_id": node_id,
                    "node_name": node_name,
                    "protocol": packet.protocol.value,
                    "direction": direction,
                    "packet_id": packet.packet_id or "",
                    "source_id": packet.source_id or "",
                    "destination_id": packet.destination_id or "",
                }
                if rssi is not None:
                    ws_payload["rssi"] = round(rssi, 1)
                if snr is not None:
                    ws_payload["snr"] = round(snr, 1)
                await ws_manager.broadcast("message_received", ws_payload)

        try:
            asyncio.get_running_loop().create_task(_save_and_notify())
        except RuntimeError:
            pass

    coord.on_packet(on_text_packet)


def _init_routes(
    coord: PipelineCoordinator,
    config: AppConfig,
    identity: DeviceIdentity,
    tx_service: TxService | None = None,
    message_repo: MessageRepository | None = None,
) -> None:
    network_mapper = NetworkMapper(coord.node_repo)
    signal_analyzer = SignalAnalyzer(coord.packet_repo)
    traffic_monitor = TrafficMonitor(coord.packet_repo)

    nodes.init_routes(coord.node_repo, network_mapper)
    packets.init_routes(coord.packet_repo)
    analytics.init_routes(signal_analyzer, traffic_monitor, coord.packet_repo)
    device.init_routes(identity, ws_manager, coord.relay_manager)
    telemetry.init_routes(coord.telemetry_repo)

    meshcore_tx = None
    if tx_service and hasattr(tx_service, '_meshcore_tx'):
        meshcore_tx = tx_service._meshcore_tx

    messages.init_routes(
        tx_service=tx_service,
        message_repo=message_repo or MessageRepository(coord.database),
        node_repo=coord.node_repo,
        meshcore_tx=meshcore_tx,
        config=config,
    )

    crypto = coord._crypto if hasattr(coord, "_crypto") else None
    config_routes.init_routes(
        config=config,
        crypto=crypto,
        tx_service=tx_service,
    )


def _on_packet_received(packet: Packet) -> None:
    import asyncio
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(ws_manager.broadcast("packet", packet.to_dict()))
    except RuntimeError:
        pass
