# Network Watchdog

Every Meshpoint runs a small standalone service called `network-watchdog`
alongside the main `meshpoint` service. Its only job is to notice when WiFi
silently dies and try to bring it back without you having to drive to the
device. This page explains what it does, when it acts, and how to tune it.

For the install/service plumbing see
[Install Script](../scripts/install.sh). For unrelated WiFi setup issues
see [Common Errors > WiFi and networking](COMMON-ERRORS.md#wifi-and-networking).

---

## What it does

The watchdog runs as `network-watchdog.service` (separate from `meshpoint.service`
so a meshpoint crash never disables WiFi recovery). On startup it disables
WiFi power save on `wlan0`, then enters a loop:

1. Every **120 seconds**, ping the default gateway.
2. If the gateway does not reply, fall back to pinging `8.8.8.8`.
3. If both fail, count it as one consecutive failure.
4. After **3 consecutive failures** (about 6 minutes), restart the `wlan0`
   interface (Stage 1 recovery).
5. Reboot escalation (Stage 2) is **disabled by default** as of v0.6.5. See
   [Re-enabling auto-reboot](#re-enabling-auto-reboot) below.

A successful ping at any point resets the counter to zero. The fallback
to `8.8.8.8` exists because some consumer routers and captive-portal
networks block ICMP to the gateway itself, which would otherwise cause
the watchdog to think WiFi was down when it was actually fine.

---

## Default thresholds

All thresholds live as constants at the top of
`/opt/meshpoint/scripts/network_watchdog.py`:

| Setting | Default | Meaning |
|---|---|---|
| `CHECK_INTERVAL_SECONDS` | `120` | Seconds between connectivity checks |
| `PING_TIMEOUT_SECONDS` | `5` | How long to wait for each ping reply |
| `RESTART_THRESHOLD` | `3` | Consecutive failures before Stage 1 (interface restart) |
| `REBOOT_THRESHOLD` | `0` | Consecutive failures before Stage 2 (system reboot). `0` disables it |
| `WIFI_INTERFACE` | `wlan0` | Interface to restart on Stage 1 |
| `FALLBACK_PING_TARGET` | `8.8.8.8` | Used when gateway does not reply |

With defaults, the watchdog will restart `wlan0` after roughly 6 minutes
of no connectivity and never reboot the Pi on its own.

---

## Why auto-reboot is off by default

Earlier versions used `REBOOT_THRESHOLD = 6`, which would reboot the Pi
after 6 consecutive failures (about 12 minutes offline). On networks where
the gateway blocks ICMP, this caused infinite reboot loops: the watchdog
could not tell the difference between "WiFi is broken" and "router does
not answer pings", so it would reboot, come back up, fail to ping the
gateway, and reboot again forever.

v0.6.5 fixes both halves of that problem:

- The fallback to `8.8.8.8` means the watchdog only counts a failure when
  the Pi truly cannot reach the internet, not just when one specific host
  refuses to reply.
- `REBOOT_THRESHOLD = 0` disables the reboot escalation entirely, so even
  if something exotic causes the fallback path to also fail, the Pi will
  not nuke itself.

Stage 1 (interface restart) is unchanged and still fires at 3 failures.
That covers the actual common case: WiFi driver wedged, association lost,
DHCP lease expired without renewal. Restarting the interface fixes those
without a full reboot.

---

## Re-enabling auto-reboot

If you want the old behavior back (for example: headless deployments
with no physical access where a reboot is the lesser evil):

```bash
sudo nano /opt/meshpoint/scripts/network_watchdog.py
```

Change:

```python
REBOOT_THRESHOLD = 0
```

to:

```python
REBOOT_THRESHOLD = 6
```

Then restart the service:

```bash
sudo systemctl restart network-watchdog
```

The startup log line will confirm the new policy:

```
INFO network-watchdog: Starting network watchdog (interface=wlan0, restart=3, reboot=6)
```

When `REBOOT_THRESHOLD = 0`, that field reads `reboot=disabled`.

Note that `git pull` will not overwrite your edit unless the file changes
upstream. If a future release modifies `network_watchdog.py`, git will
either merge cleanly or flag a conflict so you know to re-apply your
threshold.

---

## Inspecting what the watchdog is doing

Live tail:

```bash
sudo journalctl -u network-watchdog -f
```

Last 50 lines:

```bash
sudo journalctl -u network-watchdog -n 50
```

Confirm it is running:

```bash
sudo systemctl status network-watchdog
```

You should see `Active: active (running)`. If it is `inactive` or
`failed`, restart it:

```bash
sudo systemctl restart network-watchdog
```

To see the per-ping detail (which target was pinged, gateway vs fallback),
temporarily switch the log level. Edit `/opt/meshpoint/scripts/network_watchdog.py`
and change `level=logging.INFO` to `level=logging.DEBUG`, then
`sudo systemctl restart network-watchdog`. Revert when you are done so the
journal does not grow with low-value entries.

---

## Disabling the watchdog entirely

If you are debugging WiFi yourself and do not want the watchdog
restarting the interface from under you:

```bash
sudo systemctl stop network-watchdog
sudo systemctl disable network-watchdog
```

Re-enable later with:

```bash
sudo systemctl enable --now network-watchdog
```

The main `meshpoint` service does not depend on the watchdog. Stopping
the watchdog does not affect packet capture, the dashboard, or anything
else.

---

## When the watchdog will not help

The watchdog only cares about WiFi (`wlan0`). It does not monitor:

- **Ethernet (`eth0`)**: if you are wired in, the watchdog still runs and
  pings, but Stage 1 recovery restarts `wlan0`, not `eth0`. On wired-only
  deployments the watchdog is effectively a no-op.
- **The cloud uplink to `meshradar.io`**: that is handled by the upstream
  WebSocket client inside the main meshpoint service, which has its own
  reconnect with exponential backoff.
- **The local dashboard**: served by the main meshpoint service, not the
  watchdog.

If any of those break, look at the main service log (`meshpoint logs`),
not the watchdog log.
