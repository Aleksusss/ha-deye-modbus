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

Not verified: a real sub-second grid dip. The stock logger stays
connected as a backup until it is.

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

Template logic (active TOU slot, grid-charge bit decoding, losses
formula, clock register encoding) can be rendered in Developer tools ->
Template with the real sensors. During development the same templates
were also rendered with plain Jinja and mocked states; that does not
replace a check in Home Assistant, whose filters differ in details.

## Not verified yet

- Register 194 on a real sub-second grid dip.
- Grid power sign during export.
- Grid-charge flag values other than 4 and 5.
- PV registers (no panels on the test install).
- Other LP1 models or firmware; RS485-to-TCP gateways other than the EW11.
