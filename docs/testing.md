# Testing

How each claim in this project was checked, with the commands and the
results on the test install (Deye SUN-6K-SG05LP1-EU-AM2-P, Elfin EW11,
Home Assistant OS). Repeat them on your own inverter before trusting
the map, especially the write tests.

## mbpoll basics

```sh
H=192.0.2.10   # your gateway
mbpoll -m tcp -a 1 -t 4 -r <ref> -c <count> -1 "$H"   # read once
mbpoll -m tcp -a 1 -t 4 -r <ref> -c <count> -l 2000 "$H"  # every 2 s, Ctrl+C to stop
mbpoll -m tcp -a 1 -t 4 -r <ref> "$H" v1 v2 v3        # write (several values: 0x10)
```

- `-r` is **1-based**: HA address + 1. HA address 184 (SOC) is `-r 185`.
- `-t 4` prints unsigned 16-bit values; a value above 32767 is
  negative (subtract 65536).
- Smoke test for a new setup: `mbpoll -m tcp -a 1 -t 4 -r 185 -c 1 -1 "$H"`
  must print the battery SOC.

## Grid connected flag (register 194) — breaker test

Verified 2026-10-06.

```sh
mbpoll -m tcp -a 1 -t 4 -r 151 -c 1 -l 1000 "$H"   # HA 150 voltage
mbpoll -m tcp -a 1 -t 4 -r 195 -c 1 -l 1000 "$H"   # HA 194 grid connected
```

Switch off the inverter's grid-input breaker for 10-15 s, then on.

Result: 194 dropped to 0 at the same moment as the voltage. When the
grid came back, the voltage returned at once but 194 stayed 0 for about
70 s (grid stability check) before going to 1. In Home Assistant both
"grid lost" and "grid restored" fired. Outage durations therefore
include about a minute of reconnect time.

Real outage, 2026-10-07 (about 18 minutes, the flat on battery):
"grid lost" and "grid restored" fired in the same minutes as the stock
logger's alerts. Duration: 18 min from register 194 vs 18 min 30 s from
the logger. This time register 150 did drop (it read 5 V during the
outage); it has held its last value in other outages, so it is still
not used for detection.

Very short dip, 2026-10-08, with Home Assistant running well past its
startup grace: `grid connected` read 0 for about 65-70 s with no gaps
in the history, and the AC voltage read about 5 V, in Home Assistant
and in the stock logger alike. "Grid lost" and "grid restored" fired,
and so did the logger's alerts. The lights did not flicker. 65-70 s is
about the reconnect hold alone, so the dip itself was short, but its
length is unknown: register 194 shows that a dip happened, not how long
it lasted. The alert timestamps (17:16) and the history (17:18-17:19)
differ by about 2 minutes; the cause was not checked.

Not verified: a dip of known sub-second length. The stock logger stays
connected as a backup until it is.

Restart during an outage, 2026-10-08: an outage from 11:41 to 15:06
(3h25m) was reported as "0h 54m", because Home Assistant restarted at
about 14:12 and the duration was measured from the sensor's
`last_changed`, which a restart resets. Fixed in
`deye_grid_outage.yaml`: the outage start is kept in restored helpers
and set only once per outage. The template logic was checked offline
(this exact case gives 3h 25m); on live hardware it is NOT verified yet.

Pending live test: switch off the grid-input breaker for about 3
minutes and restart Home Assistant in the middle, after "grid lost" has
arrived. Expected: "grid lost" once, no second one after the restart,
and a "grid restored" message with a duration of about 4 minutes (3
minutes plus the ~70 s reconnect hold). If the grid returns within the
2-minute startup grace, that message comes from the startup bootstrap
at the end of the grace ("seen after a Home Assistant restart") instead
of the normal "restored" alert; it should still give the exact duration.

## Counter widths

Verified with mbpoll: battery charge total 72/73 read `19878 / 0`
(1987.8 kWh, matching the stock logger), discharge total 74/75
`17847 / 0`, load total 85/86 `28562 / 0`. The low word comes first
(`swap: word` in HA).

Grid import: register 79 read `5001`, then `4998` — grid frequency,
not a high word. The high word is register 80. On 2026-10-06 the HA raw
sensor (78 and 80, skipping 79) read `34736,0` = 3473.6 kWh.

## Power signs, load vs inverter power

Verified 2026-10-06 while the battery charged from the grid, first idle,
then with a ~1.8 kW kettle on:

```sh
mbpoll -m tcp -a 1 -t 4 -r 170 -c 10 -l 2000 "$H"   # HA 169..178
mbpoll -m tcp -a 1 -t 4 -r 191 -c 1 -l 2000 "$H"    # HA 190 battery power
```

| | 169 grid | 175 inverter | 178 load | 190 battery |
|---|---|---|---|---|
| idle | 2645 | -2084 | 561 | -1980 |
| kettle | 3460 | -1128 | 2332 | -1106 |

- Grid: positive = import. Export sign not verified (no export here).
- 175 is inverter power, negative while it draws AC to charge.
- 178 is load (+~1770 W with the kettle); 176 equals 178, 177 is 0.
- Battery: negative = charging (positive = discharging was verified
  earlier against a falling SOC).
- grid = load − inverter exactly; 2084 W AC in vs 1980 W into the
  battery is about 5% conversion loss at idle.

## TOU block mapping

Verified against the inverter LCD: set six *distinct* values in one
block (e.g. power 3510, 3520, ... 3560 for slots 1-6) and read the block.
This is how the power block was found to start at 256, not 257. A test
with six equal values cannot detect a one-slot shift, and neither can a
read-back after a write (it writes and reads the same addresses).

## Grid-charge flag bits

Partly verified: raw 5 with the LCD "Grid" box ticked, 4 with it
cleared, in all six slots.

Pending test (changes the LCD setting of one slot that is not active;
restore it afterwards):

```sh
mbpoll -m tcp -a 1 -t 4 -r 275 -c 6 -1 "$H"   # HA 274..279
```

Tick "Gen" as well as "Grid": expected 5 -> 7. Clear "Grid": expected 6.
That would confirm bit 0 = grid, bit 1 = generator.

## Clock: single-request write

Verified 2026-10-06. Writes a time five minutes in the past, in one
0x10 request for all three registers:

```sh
mbpoll -m tcp -a 1 -t 4 -r 23 -c 3 -1 "$H"     # before
read y mo d h mi s <<< "$(date -v-5M '+%y %m %d %H %M %S')"   # macOS date
mbpoll -m tcp -a 1 -t 4 -r 23 "$H" \
  $((10#$y*256+10#$mo)) $((10#$d*256+10#$h)) $((10#$mi*256+10#$s))
mbpoll -m tcp -a 1 -t 4 -r 23 -c 3 -1 "$H"     # after
```

Result: "Written 3 references"; Clock Offset in HA went to +304 s.

## Clock: drift / DST trigger

Verified 2026-10-06, continuing the test above without a manual
resync: the `drift_check` trigger (offset over 60 s for 10 minutes)
fired about 10 minutes later and resynced the clock; the offset returned
to about 0. This is the path that corrects the clock after a DST switch.

Expected on the autumn DST night (next: 2026-10-25), not yet observed:

1. 03:05 summer time: daily check, offset ~0, no write.
2. 04:00 summer time becomes 03:00 winter time. From the next read the
   offset is about -3600 s; Clock Needs Sync turns on.
3. About 03:11 winter time `drift_check` fires and writes the correct
   time.
4. The read-back right after that write shows a **phantom +3600 s**:
   the inverter time falls in the repeated hour 03:00-04:00, which is
   ambiguous and is read as summer time. The sync script therefore
   accepts an offset of about ±3600 s as well as about 0, so this does
   not send a "could not be verified" warning.
5. A second `drift_check` around 03:22 is blocked by the one-hour
   cooldown. After 04:00 winter time the offset reads about 0 again.

Check the logbook the next morning. If the offset reached about 0
before step 3, something else (possibly the stock logger) set the
inverter clock.

## Write safety (TOU SOC control)

All verified on live hardware, 2026-10-06:

- **Snapshot survives a restart.** Set a snapshot SOC helper to an odd
  value (41), restart Home Assistant: the value stays (before the fix,
  `initial:` reset it to the YAML default).
- **Apply and Capture are blocked during Emergency.** Turn on the
  Emergency flag by hand (it is only a helper), run Apply: nothing is
  written, no "Applying" message, write lock stays off. Run Capture:
  "Snapshot capture FAILED ... Emergency mode was on", snapshot
  unchanged. Turn the flag off again.
- **Emergency full cycle.** Emergency ON wrote 100% to all six slots,
  read-back verified, the battery charged from the grid at about 2 kW.
  Emergency OFF restored the captured profile, read-back verified,
  Emergency flag and write lock off.

- **Emergency cycle from the HACS dashboard** (2026-10-11). Tapped the
  green Emergency card, confirmed: target SOC went to 100% in all
  slots, the card turned red. Tapped "Restore normal", confirmed:
  "Emergency OFF verified; restored SOC: 100/70/40/30/30/100".

## HACS dashboard (`dashboards/deye_hacs.yaml`)

Checked on the live install, 2026-10-11 (desktop Safari on an iMac
2019, and a phone):

- **TOU bars.** card-mod renders the Jinja-built gradients. A `::before`
  on the first bar's table (for the "now" time label) made Safari draw
  that bar with equal columns, and so misplaced the now line; moving
  the line and label off the table onto the "Inverter" paragraph fixed
  it, which confirmed the cause: the pseudo-element became an anonymous
  first table row, and with `table-layout: fixed` the first row sets
  the column widths. A template check now forbids pseudo-elements on
  the tables. After the fix the now line sat right after the 19:00
  boundary at 19:09.
- **Now / next card** showed slot 4 (15:00-19:00) with the next
  changes 23:00 -> 100% and 07:00 -> 70%, and switched to slot 5 at
  the boundary.
- **Browser load.** Safari CPU was high on the Home view only. By
  default an apexcharts card redraws on every state change of its
  entities (the power sensors change every 15 s); with
  `update_interval` (ring 1 min, charts 5 min) the load became
  negligible, with the power-flow animation still on.
- **Power flow direction** correct without `invert_state`: discharging
  571 W, the home ring was battery-colored.
- **Diagnostics**: two column sections (separate sections shared row
  heights and left a gap; `dense_section_placement` does not help, it
  only back-fills holes); no gap on desktop, logical order on the phone;
  the 7-day grid ribbon works. Outage statistics matched a real
  1-minute outage the same day.

## Inverter losses: cross-check with the SOC balance

Verified as plausible for 2026-10-07. The losses sensor cannot be
measured directly, but its daily value can be checked against two
independent numbers.

Per day (00:00 to 00:00), read:

- the losses sensor's growth (Energy dashboard, individual devices);
- battery charge and discharge today (registers 70 / 71);
- battery SOC at both midnights, and the pack's usable energy
  (nominal: cells x 3.2 V x Ah).

Then:

1. Stored-energy change = (SOC end - SOC start) x pack energy.
2. Battery-internal loss = charge - discharge - stored-energy change.
   This happens inside the pack and is NOT part of the losses sensor.
3. The losses sensor covers the inverter only: AC->DC conversion while
   charging, DC->AC while discharging, standby draw. Compare its charge
   share with the conversion loss measured in the power-sign test
   (about 5%).

Test install, 2026-10-07 (one 18-minute outage that day):

| Quantity | Value |
|---|---|
| Grid import / Energy "Home" | 14.4 kWh / 14.4 kWh |
| Battery charge / discharge | 9.2 kWh / 9.2 kWh |
| Losses sensor | 1.6 kWh (about 11% of import) |
| SOC 00:00 -> 00:00 | 53% -> 49% of ~14.3 kWh (16 x 280 Ah LFP) |
| Battery-internal loss | ~0.57 kWh (~6% of charge) |

The resolution is coarse: 0.1 kWh counters and 1% SOC steps (~0.14 kWh)
put the battery-internal loss anywhere between about 0.3 and 0.9 kWh.
Of the 1.6 kWh, charge conversion at ~5% accounts for about 0.5 kWh;
the rest is discharge conversion at a low house load (~0.5 kW, where
inverters are least efficient) plus the inverter's own standby draw.

## Template checks

`tests/render_templates.py` loads the templates straight from the
packages and the dashboards and renders them with plain Jinja and mocked
states: active TOU slot and target SOC, grid-charge bit decoding, the
HACS dashboard's TOU bars (cells vs card-mod rules), losses formula,
clock register encoding and read-back check, outage duration across
restarts.
From the repository root:

```sh
python3 -m venv .venv
.venv/bin/pip install -r tests/requirements.txt
.venv/bin/python tests/render_templates.py   # exit code 1 on any FAIL
```

This checks the logic only. Home Assistant's template engine differs in
details (filters, native types), so render a template in Developer
tools -> Template with the real sensors before relying on it.

## Not verified yet

- Register 194 on a dip of known sub-second length (a very short dip
  was caught on 2026-10-08; its length is unknown).
- Grid power sign during export.
- Grid-charge flag values other than 4 and 5.
- Outage duration across a Home Assistant restart (fix of 2026-10-11).
- PV registers (no panels on the test install).
- Other LP1 models or firmware; RS485-to-TCP gateways other than the EW11.
