# ha-deye-modbus

Home Assistant YAML packages for a **Deye SUN-6K-SG05LP1-EU-AM2-P**
(6 kW single-phase hybrid) read over RS485 through an **Elfin EW11**
RS485-to-Modbus-TCP gateway, using only Home Assistant's core Modbus
integration. No custom components, no HACS, nothing that breaks when
a third-party integration stops being maintained.

Tested on one inverter. The register map was cross-checked against
public maps and then verified register by register with `mbpoll`; the
gotchas below are what that verification turned up.

## Gotchas

The main value of this repository. Each one cost real debugging time.

### The inverter ignores function 0x06

A plain `modbus.write_register` with a single number sends function
0x06 (write single register), which this inverter silently ignores.
Always pass a **list**, even for one register (`value: [70]`), so Home
Assistant sends 0x10 (write multiple registers).

### HA addresses are 0-based, mbpoll is 1-based

`address: 268` in Home Assistant is `mbpoll -r 269`. Mixing the two
shifts every reading by one register. All docs here give both.

### A failed write does not fail the action

When a Modbus write fails (timeout, no connection, exception reply),
Home Assistant logs `Pymodbus: ... Error` and the action returns
normally; the script carries on [HA core source, `modbus.py`]. The only
reliable signal is reading the registers back. Every write in this
project is followed by a read-back check.

### Read and write the clock as one block

Registers 22-24 hold year/month, day/hour, minute/second. Read them as
three separate sensors and they come from slightly different moments:
at every hour boundary the decoded time was off by an hour, and the
"offset" jumped to about 3600 s. Read all three in one request
(`structure: ">3H"`), compute the new time from **one** `now()`, and
write all three in **one** 0x10 request.

### DST: the daily sync runs before the switch

A daily clock check at 03:05 runs *before* the autumn switch at 04:00,
so the inverter would run an hour off — and shift every TOU slot by an
hour — until the next day. This project also syncs when the offset has
stayed over 60 s for 10 minutes, at most once per hour.

### Lifetime counters are 32-bit, low word first

Battery charge/discharge and load totals are 32-bit with the **low**
word in the first register (`data_type: uint32`, `swap: word`).

### Grid import total is 32-bit, but not contiguous

The grid import counter has its low word in register 78 and its high
word in register **80**. Register 79 between them is grid frequency
(values like 5001 = 50.01 Hz). Reading 78 as `uint32` glues the
frequency on as the high word.

Core Modbus cannot combine non-contiguous registers, so 78-80 are read
in one request with `structure: ">HxxH"` (the pad bytes skip 79) and a
template sensor computes `(high * 65536 + low) * 0.1`.

### The 16-bit grid import register wraps at 6553.5 kWh

Read on its own, register 78 is a 16-bit counter in 0.1 kWh steps, so it
wraps at 65535 = **6553.5 kWh**. The test install read 3473.6 kWh on
2026-10-06 (53% of the range); at roughly 15 kWh/day of grid import a
16-bit-only sensor would wrap in about 200 days. Lifetime counters that
look fine today can still be 16-bit; check the high word.

The template sensor also has an availability guard: an all-zero read
becomes a gap instead of a "meter reset", which would otherwise make the
Energy dashboard count the whole lifetime total a second time.

### Register 175 is inverter power, not load

Register 175 is often labelled "total power" and used as house load. It
is the **inverter's** power, negative while the inverter draws AC to
charge the battery. House load is register **178**. Measured while
charging from the grid: grid 2645 W, inverter -2084 W, load 561 W;
grid = load − inverter exactly.

Signs: grid power positive = import; battery power positive =
discharge, negative = charge.

### Detect outages with register 194, not the AC voltage

The AC voltage (register 150) can hold its last value while the grid is
down. Register 194 ("grid connected", the inverter's grid relay) drops
to 0 instantly and, when the grid returns, stays 0 for about 70 s while
the inverter checks grid stability. A 5 s poll cannot miss an outage,
and outage durations include that minute of reconnect time.

### TOU registers: four blocks, and the power block is easy to shift

| Block | HA addresses | mbpoll (1-based) |
|---|---|---|
| Start time (HHMM) | 250-255 | 251-256 |
| Power (W) | **256**-261 | 257-262 |
| SOC target (%) | 268-273 | 269-274 |
| Grid-charge flags | 274-279 | 275-280 |

The power block starts at 256, directly after the start times. Mapping
it one register late shifts every slot by one, which goes unnoticed
while all six slots hold the same power. Verify block mappings by
setting six *distinct* values on the inverter LCD; a read-back after a
write cannot catch a shift, because it reads the same wrong addresses.

### Grid-charge flags are a bit field

Registers 274-279 read 5 with the LCD "Grid" box ticked and 4 without.
That is not an on/off code: bits 0-1 are the charge source (1 = grid),
bits 2-4 the slot mode (4 = "General"). Test bit 0, not `== 5`.

### `initial:` disables restore_state

An `input_number` or `input_text` with `initial:` is reset to that value
on **every** restart. A saved TOU snapshot defined that way silently
went back to its YAML defaults after each restart, while its "valid"
flag (no `initial:`) stayed on — so "restore" wrote the defaults. Use
`initial:` only where a reset on restart is the point (a startup grace
flag).

### One file for all Modbus sensors

Each `modbus:` entry creates a hub, and packages do not merge hubs. A
second entry with the same hub name **or the same host:port** passes
the configuration check but is **not loaded, with all its sensors**;
the only trace is a Repairs issue ("... is duplicate, not loaded!")
[HA core source, `modbus/validators.py`]. Every Modbus sensor lives in
`deye_modbus.yaml`; the other packages only add templates.

### Moving an entity to another platform keeps its statistics only by hand

The entity registry keys entries on (domain, platform, unique_id), so a
template sensor cannot take over a Modbus sensor's entry even with the
same `unique_id`. The tested procedure — remove, delete the orphan, add
the template on the freed entity id — is in
[docs/migration.md](docs/migration.md).

## What it provides

Core (`packages/`):

| File | Content |
|---|---|
| `deye_modbus.yaml` | Hub `deye_elfin`, every Modbus sensor, 32-bit grid import |
| `deye_clock.yaml` | Decoded clock, offset, sync script, automatic sync (daily, startup, drift/DST) |
| `deye_tou.yaml` | TOU schedule, read-only: times, power, grid-charge flags |
| `deye_tou_control.yaml` | TOU SOC snapshot, Apply, Emergency 100% with write lock and read-back |
| `deye_notify.yaml` | The one notification script; edit its targets |

Optional (`packages/optional/`):

| File | Content |
|---|---|
| `deye_grid_outage.yaml` | Grid available, outage duration and statistics, lost/restored/low-SOC alerts |
| `deye_inverter_losses.yaml` | Inverter losses as an Energy dashboard device |
| `deye_pv_split.yaml` | Estimated PV1 / PV2 daily energy |

Example dashboard: `dashboards/deye.yaml` (built-in cards only).

The project writes to the inverter in exactly two places: the clock
(22-24) and the six TOU SOC targets (268-273). Nothing else is ever
written. See [docs/registers.md](docs/registers.md).

## Quick start

Requirements: Home Assistant with packages enabled, and a Modbus TCP
endpoint for the inverter's RS485 port. Gateway setup is out of scope;
it is ready when this prints the battery SOC:

```sh
mbpoll -m tcp -a 1 -t 4 -r 185 -c 1 -1 <gateway-ip>
```

1. Enable packages in `configuration.yaml`:
   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```
2. Add the gateway address to `secrets.yaml`:
   ```yaml
   deye_modbus_host: 192.0.2.10
   ```
3. Copy the core files from `packages/` into the `packages/` folder of
   your Home Assistant configuration directory, plus any optional
   modules you want.
4. In `deye_notify.yaml`, fill in `notify_entities` and/or
   `notify_actions`. Left empty, messages appear as persistent
   notifications.
5. Developer tools -> YAML -> Check configuration, then restart.
6. Check that the clock offset is near 0 and the TOU schedule matches
   the inverter LCD.
7. Before using any TOU control: press **Capture** once. It saves the
   current SOC profile as the snapshot and fills the drafts. Until then
   Apply and Emergency are blocked.
8. Optional: paste `dashboards/deye.yaml` into a new dashboard's raw
   configuration editor.

If your Energy dashboard has solar or grid export configured, set the
PV and export counters in `deye_inverter_losses.yaml`; see its header.

## Verified on hardware

On the test install, 2026-10-06 unless noted. Procedures and raw
results: [docs/testing.md](docs/testing.md).

- Register 194 as outage signal: breaker test, 10-15 s outage, both
  alerts fired, ~70 s reconnect hold.
- A real grid outage (2026-10-07, about 18 minutes): "lost" and
  "restored" fired in the same minutes as the stock logger's alerts;
  duration 18 min here vs 18 min 30 s from the logger.
- Inverter losses daily value (2026-10-07): 1.6 kWh, about 11% of grid
  import, consistent with the measured charge conversion loss and a
  cross-check against the battery SOC balance.
- 32-bit counters (72/73, 74/75, 85/86) with mbpoll; grid import split
  78 + 80 with 79 = frequency.
- Single-request clock write (0x10, 3 registers).
- Drift/DST trigger: a +304 s offset was corrected about 10 minutes
  later.
- Register 175 = inverter power, 178 = load; grid and battery signs.
- TOU block mapping against the LCD.
- TOU snapshot survives restarts; Apply and Capture blocked during
  Emergency.
- Emergency ON/OFF full cycle with read-back.
- Grid import migration to the 32-bit template sensor without losing
  Energy statistics.

## Not verified

- Register 194 on a real sub-second grid dip. (The author still runs the
  stock logger alongside as a backup until this is confirmed.)
- Grid power sign during export (the test install never exports).
- Grid-charge flag values other than 4 and 5.
- PV registers (the test install has no panels).
- Other LP1 models or firmware versions, and RS485-to-TCP gateways
  other than the EW11.

## Use at your own risk

These packages write to an inverter that powers a home. The writes are
narrow, locked and verified, but a wrong register on a different model
or firmware could change a setting you did not intend. Verify the map
on your own inverter with `mbpoll` first, and keep the inverter's LCD
within reach the first time you use a write.

## Credits and license

Register maps cross-checked against
[kbialek/deye-inverter-mqtt](https://github.com/kbialek/deye-inverter-mqtt)
and [kellerza/sunsynk](https://github.com/kellerza/sunsynk) (both
Apache-2.0); details in [NOTICE.md](NOTICE.md). This project: MIT, see
[LICENSE](LICENSE).
