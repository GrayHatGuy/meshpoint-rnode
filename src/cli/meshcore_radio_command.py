"""Standalone CLI command to configure MeshCore companion radio frequency.

Allows switching the MeshCore USB companion's radio region without
re-running the full setup wizard.  Supports preset regions (US, EU, ANZ)
and custom manual entry.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

import yaml

from src.cli.meshcore_radio_config import (
    REGION_PRESETS,
    configure_radio,
    query_radio,
)

_REBOOT_WAIT_SECONDS = 8
_PORT_RELEASE_DELAY_SECONDS = 3

_LOCAL_CONFIG_PATH = Path("config/local.yaml")

PRESET_CHOICES = list(REGION_PRESETS.keys()) + ["custom"]

_REGION_MAP = {"EU_868": "EU"}


def run_meshcore_radio(args: argparse.Namespace) -> None:
    """Entry point called from the CLI dispatcher."""
    port = args.port or _auto_detect_port()
    if not port:
        print("  No MeshCore USB device found.")
        print("  Connect a device or specify --port manually.")
        sys.exit(1)

    _stop_service()

    print()
    print("  MeshCore Radio Configuration")
    print(f"  Port: {port}")
    print()

    _show_current(port)

    region = _resolve_region(args.region)

    if region == "custom":
        _configure_custom(port)
    else:
        _configure_preset(port, region)

    _reboot_and_redetect(port)
    _prompt_reboot_or_restart()


def _auto_detect_port() -> str | None:
    """Find the first MeshCore USB candidate port."""
    from src.cli.hardware_detect import detect_meshcore_usb_candidates

    candidates = detect_meshcore_usb_candidates()
    if candidates:
        return candidates[0]
    return None


def _stop_service() -> None:
    """Stop the meshpoint service to release the serial port.

    A short settle delay gives systemd time to fully tear down the service
    and let the kernel release the underlying tty before the next caller
    opens the port. Without this delay, callers can race the teardown and
    see "Could not read current radio settings" on the first attempt.
    """
    print("  Stopping meshpoint service...")
    subprocess.run(
        ["sudo", "systemctl", "stop", "meshpoint"],
        check=False,
        capture_output=True,
    )
    time.sleep(_PORT_RELEASE_DELAY_SECONDS)


def _prompt_reboot_or_restart() -> None:
    """Recommend a full reboot, fall back to systemctl restart if declined.

    The companion just rebooted with new radio params. Restarting just the
    meshpoint service races the still-recovering USB CDC stack and can
    leave MeshCore in a half-connected state where messages don't flow.
    A full Pi reboot resets the USB controller and lets the kernel
    re-enumerate the companion cleanly. That's the reliable path.

    If the user declines the reboot, we still restart the service so the
    Pi isn't left as a dead Meshpoint, but we warn that MeshCore may need
    a manual USB unplug to come up cleanly until the next reboot.
    """
    print("  MeshCore radio reconfigured.")
    print("  A reboot is recommended to apply the new settings cleanly.")
    print()

    try:
        choice = input("  Reboot the Pi now? [Y/n]: ").strip().lower()
    except EOFError:
        choice = ""

    if choice in ("", "y", "yes"):
        print("  Rebooting...")
        subprocess.run(["sudo", "reboot", "now"], check=False)
        return

    print("  Skipping reboot. Restarting meshpoint service for now...")
    result = subprocess.run(
        ["sudo", "systemctl", "restart", "meshpoint"],
        check=False,
        capture_output=True,
    )
    if result.returncode == 0:
        print("  Service restarted.")
        print("  Note: MeshCore may need a USB unplug or a `sudo reboot`")
        print("  to come up cleanly. Check `meshpoint logs` if messages")
        print("  fail to send.")
    else:
        print("  Failed to restart service. Run: meshpoint logs")


def _show_current(port: str) -> None:
    """Query and display the companion's current radio settings."""
    status = query_radio(port)
    if status:
        model_str = f" ({status.model})" if status.model else ""
        print(f"  Device: {status.name}{model_str}")
        print(f"  Current: {status.summary()}")
    else:
        print("  Could not read current radio settings.")
    print()


def _resolve_region(region_arg: str | None) -> str:
    """Determine the target region from arg, config, or interactive menu."""
    if region_arg:
        upper = region_arg.upper()
        mapped = _REGION_MAP.get(upper, upper)
        if mapped in REGION_PRESETS or mapped == "CUSTOM":
            return mapped.lower() if mapped == "CUSTOM" else mapped
        print(f"  Unknown region '{region_arg}'.")
        print(f"  Valid options: {', '.join(PRESET_CHOICES)}")
        sys.exit(1)

    return _interactive_menu()


def _interactive_menu() -> str:
    """Show a numbered menu and return the chosen region key."""
    options = list(REGION_PRESETS.items()) + [("custom", None)]

    print("  Available presets:")
    for i, (key, preset) in enumerate(options, 1):
        if preset:
            print(f"    {i}. {preset.label}")
        else:
            print(f"    {i}. Custom (enter manual parameters)")

    while True:
        try:
            raw = input(f"  Choice [1-{len(options)}]: ").strip()
            idx = int(raw) - 1
            if 0 <= idx < len(options):
                return options[idx][0]
        except (ValueError, EOFError):
            pass
        print(f"  Please enter a number between 1 and {len(options)}.")


def _configure_preset(port: str, region_key: str) -> None:
    """Send a known region preset to the companion radio."""
    preset = REGION_PRESETS[region_key]
    print(f"  Applying {region_key} preset: {preset.label}")

    ok = configure_radio(
        port,
        preset.frequency_mhz,
        preset.bandwidth_khz,
        preset.spreading_factor,
        preset.coding_rate,
    )
    if not ok:
        print("  Failed to configure radio. Check the device and retry.")
        sys.exit(1)


def _configure_custom(port: str) -> None:
    """Prompt for custom radio parameters and send them."""
    print("  Enter custom radio parameters:")
    try:
        freq = float(input("    Frequency MHz (e.g. 910.525): ").strip())
        bw = float(input("    Bandwidth kHz (e.g. 62.5): ").strip())
        sf = int(input("    Spreading factor (e.g. 7): ").strip())
        cr = int(input("    Coding rate (e.g. 5): ").strip())
    except (ValueError, EOFError):
        print("  Invalid input. Aborting.")
        sys.exit(1)

    print(f"  Setting radio to {freq} MHz / BW{bw} / SF{sf} / CR{cr}...")

    ok = configure_radio(port, freq, bw, sf, cr)
    if not ok:
        print("  Failed to configure radio. Check the device and retry.")
        sys.exit(1)


def _reboot_and_redetect(original_port: str) -> str:
    """Wait for companion reboot, then re-detect the port path.

    We deliberately do NOT verify the new config here. Verification
    requires opening a fresh serial handshake while the companion's
    USB CDC is still mid-enumeration after the reboot, which races
    on every kernel/hub combo we have tested. The Pi reboot prompted
    next is the actual confirmation: after the host USB stack resets,
    the runtime handshake on the next boot reads back the new config
    cleanly and surfaces it on the dashboard radio tab.
    """
    print("  Companion rebooting...")
    time.sleep(_REBOOT_WAIT_SECONDS)

    new_port = _auto_detect_port()
    if not new_port:
        print(f"  Device not found after reboot. Keeping port {original_port}.")
        new_port = original_port

    if new_port != original_port:
        # The kernel often assigns a different /dev/tty* number while the
        # old device node is still being torn down (e.g. ACM0 -> ACM1 on
        # Heltec V4). That new number is transient: after the Pi reboots
        # we recommend next, the USB stack starts fresh and the device
        # almost always re-enumerates back to the original number. So
        # pinning the transient number into local.yaml is exactly the
        # wrong move -- it leaves meshpoint pointed at a path that no
        # longer exists post-reboot. Switch to auto-detect instead so
        # the source finds the companion wherever it lands.
        print(f"  Device moved from {original_port} to {new_port}")
        _enable_auto_detect()

    print()

    return new_port


def _enable_auto_detect() -> None:
    """Switch meshcore_usb to auto-detect and clear any pinned port.

    This is the durable fix for ACM-number drift during companion
    reboots. The runtime source will scan for MeshCore-compatible USB
    devices on startup and pick whichever one shows up.
    """
    if not _LOCAL_CONFIG_PATH.exists():
        return

    with open(_LOCAL_CONFIG_PATH) as fh:
        config = yaml.safe_load(fh) or {}

    mc_usb = config.get("capture", {}).get("meshcore_usb", {}) or {}

    already_auto = mc_usb.get("auto_detect", False) is True
    no_pinned_port = mc_usb.get("serial_port") in (None, "")
    if already_auto and no_pinned_port:
        return

    mc_usb["auto_detect"] = True
    mc_usb.pop("serial_port", None)
    config.setdefault("capture", {})["meshcore_usb"] = mc_usb

    updated_yaml = yaml.dump(config, default_flow_style=False, sort_keys=False)

    try:
        with open(_LOCAL_CONFIG_PATH, "w") as fh:
            fh.write(updated_yaml)
    except PermissionError:
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as tmp:
            tmp.write(updated_yaml)
            tmp_path = tmp.name
        subprocess.run(
            ["sudo", "cp", tmp_path, str(_LOCAL_CONFIG_PATH)],
            check=True,
        )
        Path(tmp_path).unlink(missing_ok=True)

    print("  Updated config/local.yaml: meshcore_usb -> auto_detect (port unpinned)")
