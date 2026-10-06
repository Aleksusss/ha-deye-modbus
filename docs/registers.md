# Register map

Deye SUN-6K-SG05LP1-EU-AM2-P, slave 1, all holding registers
(function 0x03). Addresses are the 0-based protocol addresses used by
Home Assistant's `address:`; `mbpoll` counts from 1 by default, so its
reference is one higher.

Status:

- **Verified** — checked with a deliberate test on the inverter (see
  [testing.md](testing.md)); date given.
- **Observed** — in daily use with plausible values, not tested on
  purpose.
- **Reference** — taken from the reference maps (see `NOTICE.md`), not
  checked on this inverter.

Signed values are `int16`; scaled values give the HA `scale`.

## Clock

| HA | mbpoll | Content | Status |
|---|---|---|---|
| 22 | 23 | high byte: year - 2000, low byte: month | Verified |
| 23 | 24 | high byte: day, low byte: hour | Verified |
| 24 | 25 | high byte: minute, low byte: second | Verified |

Read as one 3-register block. Written as one 3-register 0x10 request
(verified 2026-10-06).

## Energy counters (0.1 kWh)

| HA | mbpoll | Content | Width | Status |
|---|---|---|---|---|
| 70 | 71 | Battery charge today | 16 | Observed |
| 71 | 72 | Battery discharge today | 16 | Observed |
| 72-73 | 73-74 | Battery charge total | 32, low word first | Verified (mbpoll) |
| 74-75 | 75-76 | Battery discharge total | 32, low word first | Verified (mbpoll) |
| 76 | 77 | Grid import today | 16 | Observed |
| 77 | 78 | Grid export today | 16 | Reference (no export on test install) |
| 78 + **80** | 79 + 81 | Grid import total | 32, low 78, high **80** | Verified |
| 79 | 80 | Grid frequency (0.01 Hz) — sits inside the counter | 16 | Verified (5001 / 4998) |
| 84 | 85 | Load today | 16 | Observed |
| 85-86 | 86-87 | Load total | 32, low word first | Verified (mbpoll) |
| 107 | 108 | PV energy today | 16 | Reference (no PV on test install) |

The 16-bit part of grid import (78) wraps at 6553.5 kWh; the test
install read 3473.6 kWh on 2026-10-06.

## Temperatures (raw = (°C + 100) × 10)

| HA | mbpoll | Content | Status |
|---|---|---|---|
| 90 | 91 | DC (radiator) temperature | Observed |
| 91 | 92 | AC temperature | Observed |
| 182 | 183 | Battery temperature | Observed |

## PV

| HA | mbpoll | Content | Scale | Status |
|---|---|---|---|---|
| 109 | 110 | PV1 voltage | 0.1 V | Reference |
| 110 | 111 | PV1 current | 0.1 A | Reference |
| 111 | 112 | PV2 voltage | 0.1 V | Reference |
| 112 | 113 | PV2 current | 0.1 A | Reference |
| 186 | 187 | PV1 power | 1 W | Reference |
| 187 | 188 | PV2 power | 1 W | Reference |

The test install has no panels; these read 0.

## AC, grid, load

| HA | mbpoll | Content | Sign / scale | Status |
|---|---|---|---|---|
| 150 | 151 | AC L1 voltage | 0.1 V | Observed. Can hold its last value during an outage — not an outage signal |
| 151 | 152 | AC L2 voltage | 0.1 V | Reference (single-phase install) |
| 169 | 170 | Grid power | + import | Verified 2026-10-06. Export sign not verified |
| 173 | 174 | AC L1 power | signed | Observed |
| 174 | 175 | AC L2 power | signed | Reference |
| 175 | 176 | **Inverter** power (not load) | − while charging from AC | Verified 2026-10-06 |
| 176 | 177 | Load L1 power | signed | Verified (= 178 on single phase) |
| 177 | 178 | Load L2 power | signed | Verified (0 on single phase) |
| 178 | 179 | **Load** power | signed | Verified 2026-10-06 |
| 192 | 193 | AC frequency | 0.01 Hz | Observed |
| 194 | 195 | Grid connected (relay): 1 / 0 | flag | Verified 2026-10-06 (breaker test) |

176 and 177 are not read by the packages; listed for completeness.

Measured 2026-10-06 while charging from the grid (idle / kettle on):

| | 169 grid | 175 inverter | 178 load | 190 battery |
|---|---|---|---|---|
| idle | 2645 | -2084 | 561 | -1980 |
| kettle | 3460 | -1128 | 2332 | -1106 |

grid = load − inverter in both rows (2645 = 561 + 2084).

## Battery

| HA | mbpoll | Content | Sign / scale | Status |
|---|---|---|---|---|
| 183 | 184 | Battery voltage | 0.01 V | Observed |
| 184 | 185 | Battery SOC | % | Observed |
| 190 | 191 | Battery power | + discharge, − charge | Verified (both signs) |
| 191 | 192 | Battery current | 0.01 A, signed | Observed |

## BMS

| HA | mbpoll | Content | Scale | Status |
|---|---|---|---|---|
| 312 | 313 | BMS charging voltage | 0.01 V | Observed |
| 313 | 314 | BMS discharge voltage | unknown, exposed raw | Reference |
| 314 | 315 | BMS charge current limit | A | Observed |
| 315 | 316 | BMS discharge current limit | A | Observed |
| 316 | 317 | BMS SOC | % | Observed |
| 317 | 318 | BMS voltage | 0.01 V | Observed |
| 318 | 319 | BMS current | unknown, exposed raw | Reference |
| 319 | 320 | BMS temperature | (°C + 100) × 10 | Observed |

## TOU program (six slots)

| HA | mbpoll | Content | Status |
|---|---|---|---|
| 250-255 | 251-256 | Start time, HHMM as decimal (2330 = 23:30) | Verified (LCD) |
| 256-261 | 257-262 | Power, W | Verified (six distinct LCD values) |
| 268-273 | 269-274 | SOC target, % — **written** by this project | Verified (LCD, read-back, Emergency cycle) |
| 274-279 | 275-280 | Flags: bits 0-1 charge source, bits 2-4 mode | Partly verified |

Flags (layout from kellerza/sunsynk): bits 0-1 = 0 none, 1 grid,
2 generator, 3 grid + generator; bits 2-4 = mode (1 << 2 = "General").
Observed values: 5 (grid charge on, mode General) and 4 (off, General).
Other values are not verified.

## Writes

Only two register ranges are ever written, always with function 0x10
(the inverter ignores 0x06):

| HA | What | Verified |
|---|---|---|
| 22-24 | Clock, one 3-register request | 2026-10-06 |
| 268-273 | TOU SOC targets, one 6-register request | 2026-10-06 (Emergency ON/OFF cycle) |
