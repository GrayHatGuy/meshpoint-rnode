# Configuration Guide

All settings live in `config/default.yaml` with user overrides in `config/local.yaml`. The service merges both files at startup: anything in `local.yaml` overrides the default. You only need to add the settings you want to change.

Edit your local config:

```bash
sudo nano /opt/meshpoint/config/local.yaml
```

Restart after any config change: `sudo systemctl restart meshpoint`

---

## Radio

```yaml
radio:
  region: "US"                 # US, EU_868, ANZ, IN, KR, SG_923
  frequency_mhz: 906.875      # auto-configured from region
  spreading_factor: 11         # SF11 (LongFast)
  bandwidth_khz: 250.0
```

The region sets the base frequency, spreading factor, and bandwidth automatically. You only need `region` in most cases. Override `frequency_mhz`, `spreading_factor`, or `bandwidth_khz` individually to tune for non-default presets (MediumFast, ShortFast, etc.) or custom frequency slots.

### Changing Region

```yaml
radio:
  region: "EU_868"
```

To also update your MeshCore companion radio:

```bash
meshpoint meshcore-radio EU
```

Or enter a custom frequency: `meshpoint meshcore-radio custom`

See the [Onboarding Guide](ONBOARDING.md#changing-meshcore-radio-frequency) for full details.

---

## Capture Sources

```yaml
capture:
  sources:
    - concentrator             # SX1302/SX1303 8-channel LoRa
    - meshcore_usb             # optional MeshCore USB companion
  meshcore_usb:
    auto_detect: true          # scans /dev/ttyUSB* and /dev/ttyACM*
    serial_port: null           # or set explicitly: "/dev/ttyACM0"
    baud_rate: 115200
```

The setup wizard configures sources automatically. To add or remove a MeshCore companion later, edit `sources` and restart.

---

## Private Channel Monitoring

By default, the Meshpoint decrypts traffic on the standard Meshtastic default key (`AQ==`). To also decode packets on your private channels, add the channel keys to `local.yaml`:

```yaml
meshtastic:
  channel_keys:
    MyChannel: "base64encodedPSK=="
    AnotherChannel: "anotherBase64PSK=="
```

**Finding your channel's PSK:** Open the Meshtastic app, go to the channel settings, and copy the pre-shared key (base64 format).

**Channel name must match exactly** what's configured on your Meshtastic node (case-sensitive).

The Meshpoint tries each configured key when decoding a packet. Packets matching any configured key will be fully decoded. Packets on channels with unknown keys will continue to show as ENCRYPTED.

> **MeshCore private channels:** multi-key decryption for MeshCore is on the roadmap but not yet implemented. Currently only the default MeshCore key is tried.

To change the default Meshtastic key (if your primary channel uses a non-default PSK):

```yaml
meshtastic:
  default_key_b64: "yourPrimaryKeyBase64=="
```

---

## Smart Relay

Connect a separate radio (T-Beam, Heltec, RAK4631) via USB to re-broadcast captured packets:

```yaml
relay:
  enabled: true
  serial_port: "/dev/ttyACM1"  # relay radio serial port
  serial_baud: 115200
  max_relay_per_minute: 20     # token-bucket rate limit
  burst_size: 5                # max burst before throttle
  min_relay_rssi: -110.0       # ignore weak packets
  max_relay_rssi: -50.0        # ignore local packets (too strong)
```

The relay path is independent from RX: transmission never blocks packet reception. Packets are deduplicated by ID, rate-limited, and filtered by signal strength before relay.

---

## Upstream (Cloud)

```yaml
upstream:
  enabled: true
  url: "wss://api.meshradar.io"
  reconnect_interval_seconds: 10
  buffer_max_size: 5000        # local buffer during disconnects
  auth_token: null             # set by setup wizard
```

When enabled, the Meshpoint connects to [Meshradar](https://meshradar.io) via WebSocket and relays captured packets for aggregated mesh intelligence. The connection auto-reconnects with backoff and buffers packets locally during outages.

Disable upstream to run fully offline:

```yaml
upstream:
  enabled: false
```

---

## Storage

```yaml
storage:
  database_path: "data/concentrator.db"
  max_packets_retained: 100000
  cleanup_interval_seconds: 3600
```

Packets are stored in a local SQLite database. Old packets are pruned automatically based on `max_packets_retained`.

---

## Dashboard

```yaml
dashboard:
  host: "0.0.0.0"             # listen on all interfaces
  port: 8080
  static_dir: "frontend"
```

Access at `http://<pi-ip>:8080`. Bind to `127.0.0.1` to restrict to local access only.

---

## Device Identity

```yaml
device:
  device_name: "My Meshpoint"
  latitude: 42.3601
  longitude: -71.0589
  altitude: 25
```

Set during the setup wizard. The coordinates are used for map placement on the Meshradar cloud dashboard.

---

## Full Default Config

See [config/default.yaml](../config/default.yaml) for all available settings and their defaults.
