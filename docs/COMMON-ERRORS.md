# Common Errors

Searchable catalog of error messages, their cause, and the fix. Use Ctrl+F /
Cmd+F to find your message. For longer diagnostic flows see
[Troubleshooting](TROUBLESHOOTING.md). For configuration syntax see
[Configuration](CONFIGURATION.md).

If your error is not listed, capture it from `meshpoint logs` and open a
[GitHub Issue](https://github.com/KMX415/meshpoint/issues) or ask in
[Discord](https://discord.gg/BnhSeFXVY8).

---

## Install and pip

### `error: externally-managed-environment`

**Cause:** Raspberry Pi OS Bookworm and later use PEP 668 externally-managed
environments. The system `pip` refuses to install packages to protect the
OS Python.

**Fix:** Always use the Meshpoint venv path:

```bash
sudo /opt/meshpoint/venv/bin/pip install -r /opt/meshpoint/requirements.txt
```

The full update one-liner is:

```bash
cd /opt/meshpoint
sudo git pull origin main
sudo /opt/meshpoint/venv/bin/pip install -r requirements.txt
sudo systemctl restart meshpoint
```

### `No module named 'src'`

**Cause:** `/opt/meshpoint` is missing source files, or the service is
running from the wrong working directory.

**Fix:** Check that the source is intact:

```bash
ls /opt/meshpoint/src/main.py
```

If missing, re-clone (preserve your config and database first):

```bash
sudo cp -r /opt/meshpoint/data /tmp/meshpoint-data-backup
sudo cp /opt/meshpoint/config/local.yaml /tmp/local-yaml-backup
sudo rm -rf /opt/meshpoint
sudo git clone https://github.com/KMX415/meshpoint.git /opt/meshpoint
sudo cp -r /tmp/meshpoint-data-backup /opt/meshpoint/data/
sudo cp /tmp/local-yaml-backup /opt/meshpoint/config/local.yaml
sudo bash /opt/meshpoint/scripts/install.sh
```

### `No module named 'psutil'` (or `paho`, etc.)

**Cause:** A required Python dependency is missing from the venv. Often
happens after `git pull` brings in new code that depends on a newly-added
package, but `pip install` was not re-run.

**Fix:**

```bash
cd /opt/meshpoint
sudo /opt/meshpoint/venv/bin/pip install -r requirements.txt
sudo systemctl restart meshpoint
```

### `SyntaxError: source code string cannot contain null bytes` or `fatal: loose object is corrupt`

**Cause:** SD card took a bad write, usually from a hard power cut.

**Fix:** Clean re-clone preserving data and config. See
[Troubleshooting > Recovering from a corrupted install](TROUBLESHOOTING.md#recovering-from-a-corrupted-install).

---

## Service and permissions

### `Permission denied: /dev/spidev0.0`

**Cause:** The `meshpoint` system user is not in the `spi` group.

**Fix:**

```bash
sudo usermod -a -G spi meshpoint
sudo systemctl restart meshpoint
```

### `no GPIO tool found (pinctrl or gpioset)`

**Cause:** The concentrator reset script needs `pinctrl` (Pi OS Lite default)
or `gpioset` (from `gpiod`) to toggle GPIO. Non-standard images may have
neither.

**Fix:**

```bash
sudo apt install -y gpiod
sudo systemctl restart meshpoint
```

### `attempt to write a readonly database`

**Cause:** SQLite file or its directory has wrong ownership / permissions
after a re-clone or migration.

**Fix:**

```bash
sudo chmod 777 /opt/meshpoint/data
sudo chmod 666 /opt/meshpoint/data/*.db
sudo systemctl restart meshpoint
```

---

## Concentrator and radio

### `Chip version 0x00`

**Cause:** Concentrator is not responding on SPI. Either not seated, SPI
disabled in `raspi-config`, or the SPI bus latched after a hard power cut.

**Fix:**

1. Confirm SPI is enabled: `sudo raspi-config` -> Interface Options -> SPI -> Enable.
2. Confirm the concentrator module is firmly seated on the carrier board.
3. Full power cycle: `sudo poweroff`, wait for green LED to stop, unplug for
   10+ seconds, then plug back in.

Normal chip versions are `0x10` (SX1302) and `0x12` (SX1303).

### `lgw_start() failed` or `Failed to set SX1250_0 in STANDBY_RC mode`

**Cause:** SPI bus latch from a hard power cut. The Meshpoint shutdown
handler holds the concentrator in reset on `sudo reboot` and
`sudo systemctl restart`, so this only appears after yanked-cable shutdowns,
breaker trips, or outages.

**Fix:** Full power cycle:

```bash
sudo poweroff
```

Wait for the green LED to stop blinking, then unplug for 10+ seconds and
plug back in. See also [Troubleshooting > Concentrator fails to start](TROUBLESHOOTING.md#concentrator-fails-to-start).

### `SX1302 concentrator started` but `0 pkt this cycle` continuously

**Cause:** Two possible causes:

1. No Meshtastic devices in range, or wrong region/frequency for your area.
2. The SX1250 RF front-end was damaged by repeated hard power loss, even
   though the digital SPI side recovered.

**Fix:**

1. Confirm there is a known-working Meshtastic device transmitting nearby
   (within a few meters for the test).
2. Check `meshpoint status` to confirm the configured region and frequency
   match your area's mesh.
3. If still zero packets with a known-working test device close by, the
   RAK2287 module is likely damaged and needs replacement. The Pi and
   carrier board are unaffected.

### Configured custom frequency but hearing the public channel

**Cause:** Wrong override syntax in `local.yaml`, or a stale process before
restart.

**Fix:** Confirm the `radio:` block in `local.yaml` uses the right keys (no
typos, two-space indent, no tabs):

```yaml
radio:
  region: "US"
  frequency_mhz: 918.25
  bandwidth_khz: 500.0
  spreading_factor: 9
  coding_rate: "4/5"
```

Restart and confirm the new config in the startup banner:

```bash
sudo systemctl restart meshpoint
meshpoint logs | head -40
```

The startup banner prints the actual radio config, not just the region
default. If it still shows LongFast defaults, your YAML did not parse.
Validate with:

```bash
sudo /opt/meshpoint/venv/bin/python -c "import yaml; print(yaml.safe_load(open('/opt/meshpoint/config/local.yaml')))"
```

To clear stale node history after a frequency change:

```bash
sudo systemctl stop meshpoint
sudo rm /opt/meshpoint/data/concentrator.db
sudo systemctl start meshpoint
```

See [Radio Config Explained](RADIO-CONFIG-EXPLAINED.md) for the "why"
behind each field.

### `ERROR: wrong coding rate (0) - timestamp_counter_correction`

**Cause:** This message is printed by `libloragw_sx1302.c` (Semtech's HAL),
not by the Meshpoint service. The SX1302 has heard a LoRa preamble on the
configured frequency where the explicit-header decode did not yield a
recognised coding rate (1-4). Common sources:

- Non-Meshtastic LoRa neighbours on the band (LoRaWAN gateways and
  end-devices, weather stations, asset trackers). Most common in suburban
  and urban deployments.
- Implicit-header LoRa packets from devices using fixed payload formats.
- CR_LI (long-interleaver) coding rates from newer SX126x devices that are
  not in the SX1302 enum.
- Weak or partially corrupted preambles where the header CRC fails but the
  FPGA still emits a timing entry.

It interleaves with normal service lines (`loop alive`, `heartbeat sent`,
`lgw_receive`) because the HAL writes directly to stderr, which journalctl
merges with the Python logger output.

**Impact:** None. Valid Meshtastic packets with a proper LoRa header
(CR 4/5 to 4/8) decode normally. This warning specifically means "saw
something on air, could not classify it, moving on."

**Fix:** None required. Safe to ignore.

---

## API and dashboard

### `API: unreachable` in `meshpoint status`

**Cause:** The service is running but the FastAPI server has not come up
yet. Almost always because the concentrator failed to initialize, and the
API waits for radio sync before binding.

**Fix:** Read the logs to find the underlying concentrator error:

```bash
meshpoint logs | grep -iE "lgw|sx1302|concentrator|error"
```

Then apply the matching fix from the
[Concentrator and radio](#concentrator-and-radio) section above.

If you set up a Pi without the concentrator hardware to pre-stage the
software, this is expected: the wizard will detect no concentrator and the
API will stay unreachable until the real hardware is installed.

### Dashboard does not load on `http://<pi-ip>:8080`

**Cause:** Service not yet started, or `dashboard.host` was changed to
`127.0.0.1` (local-only).

**Fix:**

```bash
meshpoint status
```

Wait 60 seconds after power-on for the service to fully start. If status
shows the service is running but the page does not load, check
`dashboard.host` in `local.yaml`. The default `0.0.0.0` listens on all
interfaces. `127.0.0.1` only allows access from the Pi itself.

---

## MeshCore companion

### MeshCore companion not receiving packets

**Cause:** Wrong firmware, wrong port, wrong frequency, or the device
was hot-plugged after the service started.

**Fix:**

1. Confirm the device is detected: `ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null`
2. Confirm USB companion firmware (not BLE): re-flash from
   [flasher.meshcore.co.uk](https://flasher.meshcore.co.uk/) and pick the
   `companion_radio_usb` variant.
3. Confirm region: `meshpoint meshcore-radio` to see the current setting,
   or run `sudo meshpoint setup` to reconfigure end-to-end.
4. Hot-plugged after service start? Unplug the device, wait 5 seconds,
   plug back in. The service auto-reconnects.

```bash
meshpoint logs | grep -i meshcore
```

### MeshCore companion grabs the wrong serial port

**Cause:** Multiple Espressif boards (Heltec, T-Beam) attached at the same
time. Auto-detect cannot reliably pick the MeshCore one, especially with
mixed Heltec V4 firmwares (see
[Hardware Matrix > Heltec V3 vs V4 USB enumeration gotcha](HARDWARE-MATRIX.md#heltec-v3-vs-v4-usb-enumeration-gotcha)).

**Fix:** Pin the port explicitly:

```yaml
capture:
  meshcore_usb:
    auto_detect: false
    serial_port: "/dev/ttyACM0"
```

Then `sudo systemctl restart meshpoint`.

---

## MQTT

### MQTT enabled but no traffic on the broker, no MQTT lines in logs

**Cause:** Three common cases. Diagnose by reading the logs right after
restart:

```bash
sudo journalctl -u meshpoint --since "5 min ago" | grep -i mqtt
```

| Log line | Meaning | Fix |
|---|---|---|
| (no MQTT lines at all) | The `mqtt:` section did not parse | Check `local.yaml` indentation: two-space indent under `mqtt:`, no tabs. Did you put the block in `default.yaml` by mistake? |
| `MQTT publishing disabled` | `enabled: true` was not set | Set `mqtt.enabled: true` in `local.yaml` |
| `paho-mqtt not installed` | The MQTT library is not in the venv | `sudo /opt/meshpoint/venv/bin/pip install paho-mqtt && sudo systemctl restart meshpoint` |
| `MQTT publisher failed to connect` | Broker / network issue at the MQTT protocol level | Check broker hostname, port, credentials. Note that `telnet broker 1883` succeeding does not guarantee the paho handshake works. |
| `MQTT publisher started as !XXXXXXXX` | Working correctly | You should see `MQTT pub rc=0 topic=...` lines as packets arrive. If not, no packets are matching your `publish_channels` allowlist. |

Most-common silent failure: missing `paho-mqtt` package after a `git pull`
that did not re-run `pip install`. See [Configuration > MQTT](CONFIGURATION.md#mqtt-feed)
for full configuration reference.

### MQTT topics show `chXX` instead of `LongFast`

**Cause:** Pre-v0.6.2 bug. The channel hash was used in the topic instead
of the resolved channel name.

**Fix:** Update to v0.6.2 or later. See
[Changelog v0.6.2](CHANGELOG.md#v062-april-16-2026).

---

## Cloud (Meshradar)

### Device not appearing on the cloud dashboard

**Cause:** Upstream is disabled, API key is wrong, or the Pi has no internet.

**Fix:**

1. Confirm `upstream.enabled: true` in your `local.yaml` (or rely on the
   default from `default.yaml`).
2. Confirm the API key was saved by the setup wizard:
   ```bash
   sudo grep -A1 upstream /opt/meshpoint/config/local.yaml | grep auth_token
   ```
   It should be a non-null token. If it is `null`, re-run `sudo meshpoint setup`.
3. Check internet: `ping -c3 meshradar.io`
4. Read upstream logs:
   ```bash
   meshpoint logs | grep -i upstream
   ```

### `Upstream 401`

**Cause:** Invalid API key.

**Fix:** Generate a new key at [meshradar.io](https://meshradar.io) under
**Account > API Keys** (the key is only shown once: copy it immediately).
Then re-run `sudo meshpoint setup` and paste the new key.

### Map dot turns red when the Pi is online

**Cause:** Cloud uses a 15-minute heartbeat threshold. Cloud-side red does
not mean the Pi is offline locally: it means the Pi has not sent a
heartbeat in 15 minutes. Common causes: WiFi drops, NAT/firewall
interference, ISP outages, or upstream WebSocket errors.

**Fix:**

1. Hardwire to Ethernet to rule out WiFi.
2. Check upstream errors:
   ```bash
   sudo journalctl -u meshpoint --since "1 hour ago" | grep -i upstream
   ```
3. If the Pi reconnects on its own after the dot turns red, this is just a
   transient blip and does not need action.

### Two Meshpoints in the fleet after re-setup

**Cause:** `sudo meshpoint setup` generated a fresh `device_id` for the new
configuration, so the cloud sees it as a new device. Old `device_id` row
remains until idle.

**Fix:** Either wait 24 hours for the orphan to drop off the map, or
hard-refresh the cloud dashboard, click the orphan card in **Fleet**, and
use the **Remove** button.

---

## TX (Native messaging)

### Messages sent from the dashboard are not received by other nodes

**Cause:** Pre-v0.6.3 bug where the primary channel name defaulted to
blank, producing channel hash `0x02` instead of `0x08`. All TX packets were
invisible to the mesh.

**Fix:** Update to v0.6.3 or later, then confirm the primary channel name
is set to `LongFast` (or your network's primary channel name) on the Radio
settings page. See [Changelog v0.6.3](CHANGELOG.md#v063-april-16-2026).

### TX disabled

**Cause:** TX is off by default.

**Fix:** Enable on the **Radio** settings page in the local dashboard once
RX is verified working. Confirm the antenna is connected before enabling
TX. See [Configuration > Transmit](CONFIGURATION.md#transmit-native-messaging).

### Received chat messages show the channel key as the sender

**Cause:** Pre-v0.6.4 bug for Meshtastic broadcasts: the conversation key
(`broadcast:meshtastic:0`) was rendered in the sender slot instead of the
node name.

**Fix:** Update to v0.6.4 or later. See [Changelog v0.6.4](CHANGELOG.md#v064-april-16-2026).

---

## Setup wizard

### Wizard crashes with `PermissionError` on the final write step

**Cause:** Wizard run without `sudo`, or run from a directory where the
relative `config/local.yaml` path does not resolve.

**Fix:** Always run the wizard with sudo:

```bash
sudo meshpoint setup
```

The wizard writes to `/opt/meshpoint/config/local.yaml`, owned by root.

### Wizard cannot detect concentrator on a working RAK V2 / SenseCap M1

**Cause:** SPI not enabled, or the concentrator is in a latched state from
a previous hard power cut.

**Fix:**

1. `sudo raspi-config` -> Interface Options -> SPI -> Enable, then `sudo reboot`.
2. After reboot, full power cycle: `sudo poweroff`, wait for green LED,
   unplug 10+ seconds, plug back in.
3. Re-run `sudo meshpoint setup`.

---

## WiFi and networking

### Pi is rebooting on its own every ~12 minutes

**Cause:** The network watchdog used to escalate to a full system reboot
after 6 consecutive failed pings (about 12 minutes). On networks where
the gateway blocks ICMP, this caused infinite reboot loops.

**Fix:** Update to v0.6.5 or later:

```bash
cd /opt/meshpoint
sudo git pull origin main
sudo systemctl restart network-watchdog
```

v0.6.5 falls back to pinging `8.8.8.8` when the gateway does not reply,
and disables auto-reboot by default. Stage 1 recovery (interface restart
at 3 failures) is unchanged. See [Network Watchdog](NETWORK-WATCHDOG.md)
for the full picture and how to re-enable auto-reboot if you want it.

### `network-watchdog` service is `failed` or `inactive`

**Cause:** The service unit was not installed, or the script was edited
in a way that prevents it from starting.

**Fix:**

```bash
sudo systemctl status network-watchdog
sudo journalctl -u network-watchdog -n 50
```

If the unit file is missing entirely, re-run the installer:

```bash
sudo bash /opt/meshpoint/scripts/install.sh
```

The main meshpoint service does not depend on the watchdog. A failed
watchdog will not affect packet capture or the dashboard, only WiFi
auto-recovery.

### WiFi keeps dropping and the watchdog cannot fix it

**Cause:** Stage 1 recovery (`ip link set wlan0 down/up`) handles wedged
drivers and lost associations, but cannot fix bad credentials, weak
signal, or a router that is itself down.

**Fix:**

1. Confirm signal: `iwconfig wlan0` (look at `Link Quality` and `Signal level`).
2. Confirm credentials: `sudo nmcli connection show` and inspect the
   active profile. If the SSID password changed, update with
   `sudo nmcli connection modify <name> wifi-sec.psk <new-pw>`.
3. Move the Pi closer to the access point as a test.
4. If the router itself is the problem, the watchdog cannot help. See
   [Network Watchdog > When the watchdog will not help](NETWORK-WATCHDOG.md#when-the-watchdog-will-not-help).
