# Radio Config Explained

What each radio knob does, why it matters, and when to deviate from the
defaults. For configuration syntax and full field reference see
[Configuration > Radio](CONFIGURATION.md#radio).

If you just want a working setup that matches the public mesh, the
defaults are correct: pick your region in the setup wizard and leave
everything else alone. This document is for users who want to tune for
custom slots, narrowband experiments, or regulatory compliance.

---

## Region

The first thing the setup wizard asks. The region selects:

- **Default frequency** within the regional ISM band
- **Allowed band limits** (you cannot set `frequency_mhz` outside these)
- **MeshCore companion preset** (frequency, BW, SF, CR for that region's
  standard MeshCore channel)

Supported regions and their defaults:

| Region | Default frequency | Allowed band | Notes |
|---|---|---|---|
| `US` | 906.875 MHz | 902.0 - 928.0 MHz | FCC Part 15 (unlicensed). 500 kHz BW required for non-hopping operation. |
| `EU_868` | 869.525 MHz | 863.0 - 870.0 MHz | ETSI EN 300 220. 1% duty cycle limit. |
| `ANZ` | 919.875 MHz | 915.0 - 928.0 MHz | AS/NZS 4268. |
| `IN` | 865.875 MHz | 865.0 - 867.0 MHz | India ISM. |
| `KR` | 922.875 MHz | 920.0 - 923.0 MHz | South Korea ISM. |
| `SG_923` | 917.875 MHz | 917.0 - 925.0 MHz | Singapore ISM. |

If you set `frequency_mhz` outside the band, the service refuses to start.
Omit `frequency_mhz` entirely to use the regional default.

---

## Spreading Factor (SF)

Controls how many "chips" of the carrier are used per data symbol. Higher SF =
slower data rate but better sensitivity (longer range, more processing gain).

| SF | Symbol time @ BW250 | Relative airtime | Sensitivity |
|---|---|---|---|
| 7 | 0.512 ms | 1x (fastest) | Lowest (shortest range) |
| 8 | 1.024 ms | 2x | |
| 9 | 2.048 ms | 4x | |
| 10 | 4.096 ms | 8x | |
| 11 | 8.192 ms | 16x | |
| 12 | 16.384 ms | 32x (slowest) | Highest (longest range) |

Higher SF gives more **processing gain** at the receiver: it averages over
a longer symbol, recovering signals deeper in the noise. The cost is
airtime: an SF12 packet takes 32x longer than SF7 to transmit, eating
duty-cycle budget and increasing collision probability.

---

## Bandwidth (BW)

The width of the LoRa channel. Wider BW transmits faster but spreads the
signal across more spectrum, raising the noise floor seen by the demodulator.

| BW (kHz) | Notes |
|---|---|
| 62.5 | Used by MeshCore on most regions. **Not receivable on the SX1302 concentrator** (see note below); requires a USB companion radio |
| 125 | Narrower, slower, slightly more sensitive at the same SF |
| 250 | Meshtastic standard for most presets |
| 500 | Wider, faster, **required for non-hopping operation under FCC Part 15 in the 902-928 MHz band** |

US Part 15 is the practical reason most US Meshpoints stay on BW 250 by
default (LongFast preset) and only move to BW 500 when running a non-hopping
custom slot.

### SX1302 minimum bandwidth

The SX1302 concentrator used by every Meshpoint platform (RAK V2, SenseCap
M1, RAK2287 DIY) has a hardware floor of **125 kHz**. Anything narrower
(notably MeshCore's default 62.5 kHz) cannot be demodulated regardless of
`bandwidth_khz` setting. For sub-125 kHz signals use a
[USB companion radio](HARDWARE-MATRIX.md#meshcore-usb-companion-radios).

---

## Coding Rate (CR)

Forward error correction overhead. `4/5` adds 25% overhead, `4/8` doubles
the payload. Higher CR = better packet recovery in marginal conditions, at
the cost of throughput.

Meshtastic standard is `4/5`. Almost no reason to change.

---

## Standard Meshtastic Presets

Combinations of SF + BW that the Meshtastic firmware exposes as named
presets. The cloud and most apps assume these:

| Preset | SF | BW (kHz) | Use case |
|---|---|---|---|
| ShortTurbo | 7 | 500 | Maximum throughput, very short range |
| ShortFast | 7 | 250 | Fast, short range |
| ShortSlow | 8 | 250 | Slightly more reliable |
| MediumFast | 9 | 250 | Balanced for medium-density meshes |
| MediumSlow | 10 | 250 | More range, slower |
| **LongFast (default)** | 11 | 250 | Standard public Meshtastic channel everywhere |
| LongModerate | 11 | 125 | Same SF, narrower band |
| LongSlow | 12 | 125 | Maximum range, very slow |

Set both `spreading_factor` and `bandwidth_khz` to match a preset. If you
omit them, the service uses the region's LongFast defaults.

---

## Custom Frequency Slots

Why you would deviate from the regional default frequency:

1. **You want a private channel that does not collide with the public mesh.**
   Public Meshtastic on US915 is on `906.875` (LongFast slot). Picking a
   different frequency in the band gives you a quiet experimental channel.
2. **Regulatory compliance.** Under FCC Part 15 in the US, narrowband
   non-hopping operation in 902-928 MHz is not authorized. Running BW 500
   with a moderate SF (e.g. SF9) is one common compliant configuration.
3. **You are testing or measuring.** Range tests, link budget validation,
   coverage characterization.

Example: 918.25 MHz, BW 500, SF 9, CR 4/5 (FCC Part 15 compliant
non-hopping configuration with good interference rejection):

```yaml
radio:
  region: "US"
  frequency_mhz: 918.25
  bandwidth_khz: 500.0
  spreading_factor: 9
  coding_rate: "4/5"
```

After changing the radio config, clearing local node and packet history
gives you a clean view of who is on the new slot:

```bash
sudo systemctl stop meshpoint
sudo rm /opt/meshpoint/data/concentrator.db
sudo systemctl start meshpoint
```

---

## TX Power

```yaml
radio:
  tx_power_dbm: 22
transmit:
  enabled: false        # opt-in
  tx_power_dbm: 14
```

Two separate `tx_power_dbm` values exist:

- `radio.tx_power_dbm` (max 27): the SX1302 concentrator hardware ceiling.
  Affects what the chip is *capable* of producing.
- `transmit.tx_power_dbm` (default 14): the actual power used for native
  messaging from the dashboard. This is what you adjust day to day.

14 dBm (~25 mW) is conservative and compliant in most regions. Raise
carefully and check your regional ISM band limits before going above
20 dBm. Excess power into a poor antenna or improper grounding can damage
the radio.

---

## Duty Cycle

```yaml
transmit:
  max_duty_cycle_percent: 1.0
```

The percent of wall-clock time the radio is permitted to transmit. ETSI
(Europe) limits unlicensed 868 MHz operation to 1% duty cycle. The default
1.0 is EU-safe and a reasonable shared-spectrum practice everywhere.

US users with FCC Part 97 (amateur) authorization can raise this, but
sensible defaults protect the mesh from one Meshpoint hogging the channel.

---

## Sync Word and Preamble

```yaml
radio:
  sync_word: 0x2B
  preamble_length: 16
```

`sync_word: 0x2B` is the Meshtastic standard. The `scripts/patch_hal.sh`
step in the v0.6.0 update specifically patches the libloragw HAL to use
this sync word for both RX and TX. **Do not change** unless you know
exactly why. Changing it will make your Meshpoint invisible to the
public mesh.

`preamble_length: 16` is the Meshtastic standard. Same advice.

---

## How the Radio Settings Page Maps to Config

Every field on the **Radio** settings page in the dashboard writes the
matching key in `local.yaml` and triggers a service restart:

| Dashboard field | Config key |
|---|---|
| Region | `radio.region` |
| Modem preset | `radio.spreading_factor` + `radio.bandwidth_khz` |
| Frequency | `radio.frequency_mhz` |
| TX power | `transmit.tx_power_dbm` |
| Duty cycle | `transmit.max_duty_cycle_percent` |
| TX enabled toggle | `transmit.enabled` |
| Long name | `transmit.long_name` |
| Short name | `transmit.short_name` |
| Hop limit | `transmit.hop_limit` |
| Channel 0 (primary) name | `meshtastic.primary_channel_name` |
| Custom channel + PSK | `meshtastic.channel_keys` |

Editing the YAML directly and restarting (`sudo systemctl restart meshpoint`)
has the exact same effect.

---

## Diagnosing What the Radio is Actually Doing

After any radio config change, the startup banner prints the actual
runtime configuration. Read the first 40 lines of the log:

```bash
meshpoint logs | head -40
```

Look for the radio summary block. If it shows the regional defaults when
you expected a custom slot, your YAML did not parse: validate with

```bash
sudo /opt/meshpoint/venv/bin/python -c "import yaml; print(yaml.safe_load(open('/opt/meshpoint/config/local.yaml')))"
```

Or use `meshpoint report` for a full operational view including current
radio config, traffic counts, signal averages, and system metrics.

---

## See Also

- [Configuration > Radio](CONFIGURATION.md#radio): full field reference
- [FAQ](FAQ.md#i-want-to-listen-on-a-custom-slot-bw500-sf9-custom-mhz-is-that-supported): quick answers
- [Common Errors > Configured custom frequency but hearing the public channel](COMMON-ERRORS.md#configured-custom-frequency-but-hearing-the-public-channel)
- [Onboarding > Changing MeshCore radio frequency](ONBOARDING.md#changing-meshcore-radio-frequency)
