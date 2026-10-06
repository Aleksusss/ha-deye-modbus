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

**Status: not yet run. Planned on the author's install for 2026-10-08
evening.**

Order matters: a Modbus hub defined twice is not an error. The second
one passes the configuration check and is silently not loaded, with all
its sensors; only a Repairs issue reports it. The old files must
therefore be gone **before** the new ones arrive.

Before:

1. Full backup.
2. Emergency OFF and write lock OFF. (Deploying during Emergency would
   leave the new Emergency flag off while the inverter holds 100%.)
3. Not between 22:45 and 23:20 on the author's install (night charge
   start and its 23:15 check): the restart below must fall outside it.

Deploy:

4. **Delete the old files first.** On the author's install:
   `deye_elfin.yaml`, `deye_elfin_clock.yaml`,
   `deye_elfin_clock_status.yaml`, `deye_elfin_clock_sync.yaml`,
   `deye_elfin_clock_automation.yaml`, `deye_elfin_tou_status.yaml`,
   `deye_elfin_tou_soc_edit.yaml`, `deye_elfin_tou_write_test.yaml`,
   `deye_elfin_grid_notify.yaml`. Keep `deye_elfin_charge_alerts.yaml`
   (not part of these packages yet; it keeps working through
   `script.elfin_deye_notify_all` and `input_boolean.elfin_deye_system_ready`).
   Backup copies such as `*.yaml.bak.*` are not loaded [assumed:
   `!include_dir_named` reads `*.yaml` only], but moving them out of
   `packages/` removes the doubt.
5. Copy the new packages. Set `deye_modbus_host` in `secrets.yaml` and
   the targets in `deye_notify.yaml`.
6. Developer tools -> YAML -> Check configuration. It must pass, but a
   pass does NOT rule out a dropped duplicate hub; steps 8-9 do.
7. Restart.

After the restart:

8. **Settings -> System -> Repairs:** no Modbus issue ("duplicate, not
   loaded" or "missing name"). Settings -> System -> Logs: no
   "Package ... setup failed" or "duplicate key".
9. **Core sensors are live, not unavailable:**
   `sensor.elfin_deye_battery_soc`, `sensor.elfin_deye_grid_connected`,
   `sensor.elfin_deye_load_power`, `sensor.elfin_deye_grid_import_total`,
   `sensor.elfin_deye_clock_offset`, `sensor.elfin_deye_tou_soc_slot_1`
   to `_6`, `binary_sensor.elfin_deye_grid_available`.
10. **Capture first** (Emergency must be off). It fills the snapshot and
    the drafts. Until then Apply and Emergency ON are blocked.
11. Update dashboards (or paste `dashboards/deye.yaml` into a test
    dashboard first).
12. Delete orphaned entities: Settings -> Entities, search
    `deye_elfin_tou`, everything "not provided".
13. Check: Clock Offset stays near 0 (the offset template now pins the
    inverter time to HA's time zone explicitly); grid-charge slots show
    the same as before; a test call of `script.elfin_deye_notify_all`
    reaches every target.
