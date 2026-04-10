"""Interactive setup wizard for first-time Mesh Point provisioning.

Walks the user through hardware detection, API key entry, device
naming, GPS configuration, and generates config/local.yaml.
"""

from __future__ import annotations

import os
import socket
import uuid
from pathlib import Path
from typing import Optional

import yaml

from src.cli.hardware_detect import (
    HardwareReport,
    detect_all,
    print_report,
)

LOCAL_CONFIG_PATH = Path("config/local.yaml")
CLOUD_URL = "https://meshradar.io"


def _load_existing_config() -> dict:
    """Load existing local.yaml, returning empty dict if absent."""
    if not LOCAL_CONFIG_PATH.exists():
        return {}
    try:
        with open(LOCAL_CONFIG_PATH) as fh:
            data = yaml.safe_load(fh)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def run_setup() -> None:
    """Main entry point for the interactive setup wizard."""
    _print_banner()

    existing = _load_existing_config()
    if existing:
        print("  Existing config/local.yaml found.")
        print("  Press Enter at any prompt to keep the current value.")
        print()

    config: dict = {}

    report = _step_hardware_detect()
    _step_region(config, existing)
    _step_capture_source(config, report)
    _step_api_key(config, existing)
    _step_device_name(config, existing)
    _step_location(config, report, existing)
    _step_relay(config, report)
    _step_device_id(config, existing)

    _write_config(config)
    _step_start_service()


def _print_banner() -> None:
    print()
    print("  ╔══════════════════════════════════════╗")
    print("  ║     Mesh Radar -- Mesh Point Setup   ║")
    print("  ╚══════════════════════════════════════╝")
    print()


SUPPORTED_REGIONS = ["US", "EU_868", "ANZ", "IN", "KR", "SG_923"]

_REGION_LABELS = {
    "US": "US      (902-928 MHz)",
    "EU_868": "EU_868  (869 MHz -- Europe, Russia, Africa)",
    "ANZ": "ANZ     (915-928 MHz -- Australia, NZ)",
    "IN": "IN      (865-867 MHz -- India)",
    "KR": "KR      (920-923 MHz -- Korea)",
    "SG_923": "SG_923  (917-925 MHz -- Singapore, SE Asia)",
}


def _step_hardware_detect() -> HardwareReport:
    """Probe for all available hardware."""
    print("  [1/8] Detecting hardware...")
    report = detect_all()
    print_report(report)
    return report


def _step_region(config: dict, existing: dict | None = None) -> None:
    """Select the LoRa frequency region."""
    print("  [2/8] Frequency region")
    print()
    print("        Select the region that matches your local Meshtastic")
    print("        network. This determines which frequencies the")
    print("        concentrator listens on.")
    print()

    current_region = (existing or {}).get("radio", {}).get("region")
    for i, region in enumerate(SUPPORTED_REGIONS, 1):
        marker = " <-- current" if region == current_region else ""
        print(f"          {i}. {_REGION_LABELS[region]}{marker}")

    current_idx = None
    if current_region in SUPPORTED_REGIONS:
        current_idx = SUPPORTED_REGIONS.index(current_region) + 1

    prompt_suffix = f" [{current_idx}]" if current_idx else ""

    while True:
        raw = _prompt(f"Region [1-{len(SUPPORTED_REGIONS)}]{prompt_suffix}:").strip()
        if not raw and current_idx is not None:
            idx = current_idx - 1
            break
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(SUPPORTED_REGIONS):
                break
        except ValueError:
            pass
        print(f"          Please enter a number between 1 and {len(SUPPORTED_REGIONS)}.")

    region = SUPPORTED_REGIONS[idx]
    config.setdefault("radio", {})["region"] = region
    print(f"        Region set to {region}")
    print()


def _step_capture_source(config: dict, report: HardwareReport) -> None:
    """Choose the LoRa capture source based on detected hardware."""
    print("  [3/8] Capture source")

    if report.concentrator_available:
        print(f"        Concentrator detected on {report.spi_devices[0]}")
        print(f"        Hardware: {report.hardware_description}")
        source = "concentrator"
        spi_device = report.spi_devices[0]
        config["capture"] = {
            "sources": [source],
            "concentrator_spi_device": spi_device,
        }
        config.setdefault("device", {})["hardware_description"] = (
            report.hardware_description
        )
    elif report.serial_ports:
        port = _choose_from_list(
            "Select capture serial port:", report.serial_ports
        )
        config["capture"] = {
            "sources": ["serial"],
            "serial_port": port,
        }
    else:
        print("        No LoRa hardware detected.")
        print("        Connect a RAK2287 concentrator or Meshtastic serial radio")
        print("        and re-run 'meshpoint setup'.")
        config["capture"] = {"sources": []}

    _maybe_add_meshcore_usb(config, report)


def _step_api_key(config: dict, existing: dict | None = None) -> None:
    """Prompt for the Mesh Radar API key (required, signature-verified)."""
    from src.activation import verify_license_key

    print("  [4/8] API key")
    print()

    current_key = (existing or {}).get("upstream", {}).get("auth_token")
    if current_key:
        masked = current_key[:8] + "..." + current_key[-4:]
        print(f"        Current key: {masked}")
        print("        Press Enter to keep the current key, or paste a new one.")
        print()
    else:
        print("        An API key is required to activate this Mesh Point.")
        print(f"        Get a free key at {CLOUD_URL}")
        print()
        print("        Steps:")
        print("          1. Go to meshradar.io and create an account")
        print("          2. Click 'API Keys' in the top bar")
        print("          3. Generate a new key and copy it")
        print()

    while True:
        api_key = _prompt("Paste your API key:").strip()
        if not api_key and current_key:
            api_key = current_key
            break
        if not api_key:
            print("        An API key is required. Get one free at meshradar.io")
            print()
            continue
        if verify_license_key(api_key):
            break
        print("        That key is not valid. Please check and try again.")
        print()

    config["upstream"] = {
        "enabled": True,
        "auth_token": api_key,
    }
    print("        API key verified and saved.")
    print()


def _step_device_name(config: dict, existing: dict | None = None) -> None:
    """Choose a name for this Mesh Point."""
    print("  [5/8] Device name")
    current_name = (existing or {}).get("device", {}).get("device_name")
    default_name = current_name or _default_device_name()
    name = _prompt(f"Device name [{default_name}]:").strip()
    if not name:
        name = default_name

    config.setdefault("device", {})["device_name"] = name
    print(f"        Named: {name}")
    print()


def _step_location(
    config: dict,
    report: HardwareReport,
    existing: dict | None = None,
) -> None:
    """Set device GPS coordinates."""
    print("  [6/8] Location")

    gps = report.gps
    if gps.got_fix:
        print(f"        GPS fix acquired: {gps.latitude}, {gps.longitude}")
        print(f"        Altitude: {gps.altitude}m | Satellites: {gps.satellites}")
        if _confirm("Use this GPS position?", default_yes=True):
            config.setdefault("device", {}).update({
                "latitude": gps.latitude,
                "longitude": gps.longitude,
                "altitude": gps.altitude,
            })
            print()
            return

    cur_dev = (existing or {}).get("device", {})
    cur_lat = cur_dev.get("latitude")
    cur_lon = cur_dev.get("longitude")
    cur_alt = cur_dev.get("altitude")

    print("        Enter coordinates manually (used for map placement).")
    print("        Tip: in Google Maps, right-click any location and click")
    print("        the coordinates at the top of the menu to copy them.")
    print("        They copy in decimal format (e.g. 42.3601, -71.0589).")
    if cur_lat is not None and cur_lon is not None:
        print(f"        Current: {cur_lat}, {cur_lon}")
    print()

    lat = _prompt_float_with_default("Latitude (e.g. 42.3601):", cur_lat)
    lon = _prompt_float_with_default("Longitude (e.g. -71.0589):", cur_lon)
    alt = _prompt_float_with_default(
        "Altitude in meters (or Enter to skip):", cur_alt, required=False
    )

    device = config.setdefault("device", {})
    if lat is not None:
        device["latitude"] = lat
    if lon is not None:
        device["longitude"] = lon
    if alt is not None:
        device["altitude"] = alt

    print()


def _step_relay(config: dict, report: HardwareReport) -> None:
    """Configure the optional SX1262 relay radio."""
    print("  [7/8] Relay radio (optional)")

    capture_port = config.get("capture", {}).get("serial_port")
    available_ports = [
        p for p in report.serial_ports if p != capture_port
    ]

    if not available_ports:
        print("        No additional serial ports detected for relay.")
        print("        Relay can be configured later in config/local.yaml")
        print()
        return

    print("        A relay radio (SX1262) rebroadcasts packets to extend")
    print("        mesh coverage. It uses a separate serial port.")
    print()

    if _confirm("Configure a relay radio?"):
        port = _choose_from_list(
            "Select relay serial port:", available_ports
        )
        config["relay"] = {
            "enabled": True,
            "serial_port": port,
        }
        print(f"        Relay configured on {port}")
    else:
        print("        Relay skipped.")

    print()


def _step_device_id(config: dict, existing: dict | None = None) -> None:
    """Preserve existing device ID, or generate a new one."""
    current_id = (existing or {}).get("device", {}).get("device_id")
    if current_id:
        device_id = current_id
        print(f"  [8/8] Device ID: {device_id} (preserved)")
    else:
        device_id = str(uuid.uuid4())
        print(f"  [8/8] Device ID: {device_id} (new)")
    config.setdefault("device", {})["device_id"] = device_id
    print()


def _write_config(config: dict) -> None:
    """Write the generated config to config/local.yaml."""
    LOCAL_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(LOCAL_CONFIG_PATH, "w") as fh:
        yaml.dump(config, fh, default_flow_style=False, sort_keys=False)

    print(f"  Config written to {LOCAL_CONFIG_PATH}")
    print()


def _step_start_service() -> None:
    """Prompt the user to reboot so all changes take effect."""
    print("  A reboot is recommended to apply all changes.")
    print()

    if _is_systemd():
        if _confirm("Reboot now?", default_yes=True):
            print("  Rebooting...")
            import subprocess
            subprocess.run(["sudo", "reboot"], check=False)
        else:
            print("  Run 'sudo reboot' when ready. The service starts")
            print("  automatically on boot.")
    else:
        print("  Reboot the device to start the Mesh Point service.")

    print()
    print("  Setup complete!")
    print()


def _maybe_add_meshcore_usb(config: dict, report: HardwareReport) -> None:
    """Delegate MeshCore USB setup to the wizard_meshcore module."""
    from src.cli.wizard_meshcore import maybe_add_meshcore_usb
    maybe_add_meshcore_usb(config, report, _confirm, _choose_from_list)


# ── Helpers ─────────────────────────────────────────────────────────

def _prompt(message: str) -> str:
    """Print an indented prompt and read input."""
    return input(f"        {message} ")


def _confirm(message: str, default_yes: bool = False) -> bool:
    """Yes/no prompt with a default."""
    suffix = "[Y/n]" if default_yes else "[y/N]"
    answer = _prompt(f"{message} {suffix}").strip().lower()
    if not answer:
        return default_yes
    return answer in ("y", "yes")


def _prompt_float(
    message: str, required: bool = True
) -> Optional[float]:
    """Prompt for a float value."""
    while True:
        raw = _prompt(message).strip()
        if not raw:
            if required:
                print("          A value is required.")
                continue
            return None
        try:
            return round(float(raw), 6)
        except ValueError:
            print("          Please enter a valid number.")


def _prompt_float_with_default(
    message: str,
    default: Optional[float] = None,
    required: bool = True,
) -> Optional[float]:
    """Prompt for a float value with an optional pre-filled default."""
    if default is not None:
        label = f"{message} [{default}]"
    else:
        label = message
    while True:
        raw = _prompt(label).strip()
        if not raw:
            if default is not None:
                return default
            if required:
                print("          A value is required.")
                continue
            return None
        try:
            return round(float(raw), 6)
        except ValueError:
            print("          Please enter a valid number.")


def _choose_from_list(message: str, options: list[str]) -> str:
    """Present numbered options and return the chosen value."""
    print(f"        {message}")
    for i, option in enumerate(options, 1):
        print(f"          {i}. {option}")

    while True:
        raw = _prompt(f"Choice [1-{len(options)}]:").strip()
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(options):
                return options[idx]
        except ValueError:
            pass
        print(f"          Please enter a number between 1 and {len(options)}.")


def _default_device_name() -> str:
    """Generate a sensible default device name from the hostname."""
    hostname = socket.gethostname().split(".")[0]
    return f"Mesh Point {hostname.capitalize()}"


def _is_systemd() -> bool:
    """Check if we're running on a systemd-based system."""
    return os.path.isdir("/run/systemd/system")


