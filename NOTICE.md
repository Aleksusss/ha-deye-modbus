# Credits and third-party references

This project is MIT-licensed (see `LICENSE`). Register addresses were
cross-checked against the projects below and then verified on a real
Deye SUN-6K-SG05LP1-EU-AM2-P with `mbpoll`. No code or YAML from these
projects is included; they were used as register-map references only.

## kbialek/deye-inverter-mqtt

- License: Apache-2.0
- Reference (pinned commit):
  https://github.com/kbialek/deye-inverter-mqtt/blob/e9cb713defddff14296e9094beec098a5017d59a/ha_definitions/deye_hybrid_map.yaml
- Used for: the overall hybrid register map (telemetry, energy counters,
  BMS, clock).
- Note: the SG05LP1 is not in that project's list of tested models.
  Every address used here was re-checked on the actual inverter.

## kellerza/sunsynk

- License: Apache-2.0 (Copyright 2021-2026 Johann Kellerman)
- Reference (pinned commit):
  https://github.com/kellerza/sunsynk/blob/4628ca7e7431667cc47bef4e12babf4c2e732291/src/sunsynk/definitions/single_phase.py
- Used for:
  - register 194 ("Grid connected");
  - the split 32-bit grid import counter: (78, 80) "Total grid import",
    with 79 = grid frequency;
  - the TOU program registers: times 250-255, power 256-261,
    capacity (SOC) 268-273, and the bit layout of 274-279
    (bits 0-1 = charge source, bits 2-4 = mode).
