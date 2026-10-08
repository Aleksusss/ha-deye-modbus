# Migration notes

How the author's live installation moved to these packages, and what to
expect if you are upgrading from an earlier version of them.

Labels: **[verified]** = done on live hardware, date given;
**[source]** = checked in Home Assistant core source (`dev` branch,
2026-10-06), not on hardware; **[assumed]** = not checked.

## Grid Import Total: 16-bit Modbus sensor -> 32-bit template sensor

**Status: [verified] on live HA, 2026-10-06 ~20:03. Steps 1-4 worked as
written.**

Goal: replace the Modbus sensor `Elfin Deye Grid Import Total`
(16-bit, register 78) with the template sensor of the same name and
`unique_id` (32-bit, 78 + 80), keeping the entity id
`sensor.elfin_deye_grid_import_total` and its long-term statistics, which
the Energy dashboard uses.

Why it takes several steps: the entity registry keys entries on
(domain, platform, unique_id) [source: `helpers/entity_registry.py`].
The template sensor is a different platform, so it is a new registry
entry and cannot take over the old one. The old entry has to be removed
first so that its entity id becomes free.

0. **Check.** Full backup. In Developer tools compare
   `sensor.elfin_deye_grid_import_total_raw` ("low,high") with the old
   sensor. The high word must be 0, otherwise the value jumps.
   Observed: `34736,0` and `3473.6`.
1. **Remove the 16-bit Modbus block** from the YAML, check the
   configuration, restart. The old entity shows as no longer provided;
   its registry entry still holds the entity id.
2. **Delete the old entity** in Settings -> Entities. The UI only allows
   this once the entity is no longer provided [verified]. Statistics are
   kept: the recorder reacts to entity id renames, not to removals
   [source: `components/recorder/entity_registry.py`] [verified: no
   statistics lost]. Do NOT use "Fix issue -> delete" for this id in
   Developer tools -> Statistics.
3. **Add the template sensor** and reload template entities (no restart
   needed). An entity id that belonged to a deleted entity counts as
   available [source], so the new sensor gets
   `sensor.elfin_deye_grid_import_total`, generated from its `name:`.
4. **Verify.** Result on 2026-10-06 [verified]: original entity id (no
   `_2`), value 3473.6 (same as step 0), Developer tools -> Statistics:
   no issue.

Side effect: the Energy cost sensor
`sensor.elfin_deye_grid_import_total_cost` started a new cycle (state
0.0, `last_reset` at the migration time). **No impact on the daily
totals [verified 2026-10-06 21:05]:** the Energy dashboard showed
12.5 kWh of grid import for the day with no spike in any hour, and the
day's cost summed across the reset (the cost total continued after
20:03 instead of restarting from zero).

## TOU helpers renamed `deye_elfin_tou_*` -> `elfin_deye_tou_*`

**Status: not yet deployed.**

All TOU control entities moved to the project-wide `elfin_deye_` prefix,
including their `unique_id`s. They have no long-term statistics worth
keeping, so they are created fresh:

- The snapshot starts empty and `snapshot_valid` is off. Emergency ON
  and Apply stay blocked until the first Capture (fail-safe direction).
- The old entities remain in the registry as "not provided" and should
  be deleted by hand.
- The thin wrapper scripts `*_emergency_on_bot` / `*_emergency_off_bot`
  are gone; dashboards call `script.elfin_deye_tou_emergency_on` /
  `_off` directly. The separate TOU notify script is gone too; every
  package uses `script.elfin_deye_notify_all`.

## Deploy checklist

**Status: in progress on the author's install, 2026-10-08.**

Order matters: a Modbus hub defined twice is not an error. The second
one passes the configuration check and is silently not loaded, with all
its sensors; only a Repairs issue reports it. The old files must
therefore be gone **before** the new ones arrive.

Entity ids: the registry keeps an entity's id from the day it was
created. If a sensor was created under an older `name:`, its id differs
from what the current name suggests, and a dashboard or checklist built
from names points at nothing. `states()` returns `unknown` for an id
that does not exist, the same as for a real unknown state.

Before (no changes to the running system):

1. Full backup.
2. Emergency OFF and write lock OFF. (Deploying during Emergency would
   leave the new Emergency flag off while the inverter holds 100%.)
   Note the six TOU SOC values for comparison after Capture.
3. **Confirm the real ids** of existing entities that the new dashboard
   uses but the old configuration never referenced (losses total, load
   today, outage count today, grid-charge state, TOU power and
   grid-charge per slot). Paste into Developer tools -> Template:
   ```jinja
   {% for e in ['sensor.elfin_deye_inverter_losses_total',
     'sensor.elfin_deye_load_today', 'sensor.elfin_deye_grid_outage_count_today',
     'sensor.elfin_deye_tou_grid_charge_state', 'sensor.elfin_deye_tou_power_slot_1',
     'binary_sensor.elfin_deye_tou_grid_charge_slot_1'] %}
   {{ e }}: {{ 'MISSING' if states | selectattr('entity_id', 'eq', e) | list | count == 0 else states(e) }}
   {% endfor %}
   Candidates: {{ states | selectattr('entity_id', 'search', 'losses|load_today|outage_count|grid_charge|tou_power')
                 | map(attribute='entity_id') | list }}
   ```
   Any MISSING: use the real id from "Candidates" in the dashboard and in
   step 9. Do not rename the entity: Energy and statistics use its id.
4. **Create the new dashboard now**, before the restart: paste
   `dashboards/deye.yaml` into a new dashboard's raw configuration
   editor. Its cards show "not available" until step 8, then the
   Emergency button works straight away. The old dashboard keeps working
   until step 5.
5. Pick a time away from TOU slot boundaries and the night-charge
   window; the restart in step 8 must not fall on either.

Deploy:

6. **Move the old files out of `packages/` first.** On the author's
   install: `deye_elfin.yaml`, `deye_elfin_clock.yaml`,
   `deye_elfin_clock_status.yaml`, `deye_elfin_clock_sync.yaml`,
   `deye_elfin_clock_automation.yaml`, `deye_elfin_tou_status.yaml`,
   `deye_elfin_tou_soc_edit.yaml`, `deye_elfin_tou_write_test.yaml`,
   `deye_elfin_grid_notify.yaml`, plus Deye backup copies. Keep
   `deye_elfin_charge_alerts.yaml` (not part of these packages yet; it
   keeps working through `script.elfin_deye_notify_all` and
   `input_boolean.elfin_deye_system_ready`).
7. Copy the new packages; set `deye_modbus_host` in `secrets.yaml` and
   the targets in `deye_notify.yaml`. Check configuration: it must pass,
   but a pass does NOT rule out a dropped duplicate hub.
8. Restart.

After the restart (stop and roll back on any failure in 9-11):

9. **Repairs and logs:** no Modbus issue ("duplicate, not loaded");
   no "Package ... setup failed" or "duplicate key" in the log.
10. **Core sensors live.** Any `unknown` or `unavailable` is a stop:
    battery SOC, grid connected, grid available, load power, grid
    import total, clock offset (near 0), losses total, TOU SOC slots,
    one grid-charge slot.
11. **Energy dashboard:** its configuration shows no "entity not
    available" or statistics warnings, and today's graph continues
    across the restart without a gap.
12. **Capture first** (Emergency must be off). It fills the snapshot and
    the drafts; the SOC values must match step 2. Until then Apply and
    Emergency ON are blocked.
13. Delete orphaned entities: Settings -> Entities, search
    `deye_elfin_tou`, everything "not provided". Then remove the old
    dashboard's TOU view (it uses the old ids).
14. Check: a test call of `script.elfin_deye_notify_all` reaches every
    target; the grid-charge state matches the inverter LCD.

Rollback: move the new files out of `packages/`, move the old ones
back, restart. The old TOU helpers restore their previous values.
