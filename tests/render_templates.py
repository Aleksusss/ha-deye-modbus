"""Render the real templates from the packages and dashboard with mocked states.

Plain Jinja with stand-ins for the Home Assistant functions the templates
use, not Home Assistant's own template engine: filters differ in details,
so this checks the logic, not HA compatibility.

Usage (from the repository root):
    python3 -m venv .venv
    .venv/bin/pip install -r tests/requirements.txt
    .venv/bin/python tests/render_templates.py

Prints one line per check; exits 1 if any check fails.
"""
import datetime as dt
import os
import sys
import types

import jinja2
import yaml

repo = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(p):
    with open(f"{repo}/{p}", encoding="utf-8") as fh:
        return yaml.safe_load(fh.read().replace("!secret ", "secret_"))


def native(v):
    """Approximate HA's native-type parsing of rendered variables."""
    v = v.strip()
    if v in ("True", "False"):
        return v == "True"
    for t in (int, float):
        try:
            return t(v)
        except ValueError:
            pass
    return v


def _int(v, d=0):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return d


def _float(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def _is_number(v):
    try:
        float(v)
        return not isinstance(v, bool)
    except (TypeError, ValueError):
        return False


class Env:
    def __init__(self, states, now, attrs=None):
        self.s, self.n, self.a = states, now, attrs or {}
        e = jinja2.Environment()
        e.globals.update(
            states=lambda k: self.s.get(k, "unknown"),
            is_state=lambda k, v: self.s.get(k) == v,
            has_value=lambda k: self.s.get(k, "unknown") not in ("unknown", "unavailable"),
            state_attr=lambda ent, a: self.a.get((ent, a)),
            as_timestamp=lambda x, *d: x.timestamp() if hasattr(x, "timestamp") else float(x),
            now=lambda: self.n,
            namespace=jinja2.utils.Namespace,
        )
        e.filters.update(
            bitwise_and=lambda a, b: int(a) & int(b),
            is_number=_is_number,
            int=_int,
            float=_float,
            timestamp_custom=lambda ts, fmt: dt.datetime.fromtimestamp(ts).strftime(fmt),
        )
        e.tests.update(eq=lambda a, b: a == b, number=lambda v: isinstance(v, (int, float)) and not isinstance(v, bool))
        self.e = e

    def r(self, t, **kw):
        return self.e.from_string(t).render(**kw).strip()


fails = 0


def check(name, got, want):
    global fails
    ok = got == want
    fails += not ok
    print(f"{'OK ' if ok else 'FAIL'} {name}: got {got!r}" + ("" if ok else f", want {want!r}"))


d = dt.datetime(2026, 10, 6)

# ---- 1. TOU schedule table: active slot ----
dash = load("dashboards/deye.yaml")
tou_md = [c for s in dash["views"][1]["sections"] for c in s["cards"]
          if c.get("type") == "markdown" and "Grid charge |" in c.get("content", "")][0]["content"]


def tou_states(times):
    st = {}
    for i, t in enumerate(times, 1):
        st[f"sensor.elfin_deye_tou_start_time_slot_{i}"] = t
        st[f"sensor.elfin_deye_tou_soc_slot_{i}"] = str(10 * i)
        st[f"sensor.elfin_deye_tou_power_slot_{i}"] = "3500"
        st[f"binary_sensor.elfin_deye_tou_grid_charge_slot_{i}"] = "on" if i in (1, 6) else "off"
    return st


def active(out):
    rows = [ln for ln in out.splitlines() if ln.startswith("| ▶")]
    return rows[0].split("|")[2].strip() if len(rows) == 1 else f"{len(rows)} marked"


std = ["00:00", "07:00", "11:00", "15:00", "19:00", "23:00"]
out = Env(tou_states(std), d.replace(hour=3)).r(tou_md)
check("TOU 03:00 -> slot 1", active(out), "1")
check("TOU table rows", len([ln for ln in out.splitlines() if ln.startswith("|")]), 8)
check("TOU 23:30 -> slot 6", active(Env(tou_states(std), d.replace(hour=23, minute=30)).r(tou_md)), "6")
check("TOU 11:00 exact -> slot 3", active(Env(tou_states(std), d.replace(hour=11)).r(tou_md)), "3")
late = ["01:00", "07:00", "11:00", "15:00", "19:00", "23:00"]
check("TOU 00:30 before first slot -> wraps to 6", active(Env(tou_states(late), d.replace(minute=30)).r(tou_md)), "6")

# ---- 1b. TOU active slot / target SOC sensors (same rule as the table) ----
tou_pkg = {s["unique_id"]: s for s in load("packages/deye_tou.yaml")["template"][0]["sensor"]}
act_s, tgt_s = tou_pkg["elfin_deye_tou_active_slot"], tou_pkg["elfin_deye_tou_target_soc"]


def slot_at(times, hour, minute=0):
    return Env(tou_states(times), d.replace(hour=hour, minute=minute)).r(act_s["state"])


check("active slot 03:00 -> 1", slot_at(std, 3), "1")
check("active slot 11:00 exact -> 3", slot_at(std, 11), "3")
check("active slot 23:30 -> 6", slot_at(std, 23, 30), "6")
check("active slot 00:30 before first slot -> 6", slot_at(late, 0, 30), "6")
check("active slot available", Env(tou_states(std), d).r(act_s["availability"]), "True")
check("active slot unavailable on bad time",
      Env({**tou_states(std), "sensor.elfin_deye_tou_start_time_slot_4": "unknown"}, d).r(act_s["availability"]), "False")
check("target SOC = SOC of active slot", Env({**tou_states(std), "sensor.elfin_deye_tou_active_slot": "3"}, d).r(tgt_s["state"]), "30")
check("target SOC unavailable without active slot",
      Env({**tou_states(std), "sensor.elfin_deye_tou_active_slot": "unavailable"}, d).r(tgt_s["availability"]), "False")

# ---- 1c. HACS dashboard TOU bars: content cells match card-mod rules ----
hacs = load("dashboards/deye_hacs.yaml")


def bar_cards(view):
    return [c for s in view["sections"] for c in s["cards"]
            if c.get("type") == "markdown" and "<table" in c.get("content", "")]


home_bar, = bar_cards(hacs["views"][0])
tou_bars, = bar_cards(hacs["views"][1])


def hacs_states(times, socs, drafts=None):
    st = tou_states(times)
    for i, v in enumerate(socs, 1):
        st[f"sensor.elfin_deye_tou_soc_slot_{i}"] = str(v)
        st[f"input_number.elfin_deye_tou_soc_{i}_draft"] = f"{(drafts or socs)[i - 1]}.0"
        st[f"input_text.elfin_deye_tou_snapshot_time_{i}"] = times[i - 1]
        st[f"input_number.elfin_deye_tou_snapshot_soc_{i}"] = f"{v}.0"
    return st


def first_row(html):
    return html.split("</tr>")[0].count("<td ")


socs = [100, 70, 40, 30, 30, 100]
night = ["00:00", "05:00", "07:00", "17:00", "21:00", "23:00"]
e = Env(hacs_states(night, socs), d.replace(hour=23, minute=40))
html, css = e.r(home_bar["content"]), e.r(home_bar["card_mod"]["style"]["ha-markdown$"])
check("hacs bar: 6 cells", first_row(html), 6)
check("hacs bar: one css rule per cell", css.count("td:nth-child("), 6)
check("hacs bar: labels only on slots >= 3 h", html.count("%</td>"), 3)
check("hacs bar: now marker at 23:40", "left: 98.61%" in css, True)
e = Env(hacs_states(late, socs), d.replace(hour=0, minute=30))
html, css = e.r(home_bar["content"]), e.r(home_bar["card_mod"]["style"]["ha-markdown$"])
check("hacs bar: slot 1 at 01:00 adds a leading slot-6 cell", (first_row(html), css.count("td:nth-child(")), (7, 7))
check("hacs bar: no times -> message, no rules",
      (Env({}, d).r(home_bar["content"]), Env({}, d).r(home_bar["card_mod"]["style"]["ha-markdown$"]).count("nth-child")),
      ("TOU start times are not available yet.", 0))
e = Env(hacs_states(night, socs, [100, 70, 50, 30, 30, 100]), d)
html, css = e.r(tou_bars["content"]), e.r(tou_bars["card_mod"]["style"]["ha-markdown$"])
check("hacs TOU view: three bars + axis", html.count("<table"), 4)
check("hacs TOU view: one css rule per cell", css.count("td:nth-child("), 18)
check("hacs TOU view: only draft slot 3 outlined",
      [ln.split(" {")[0] for ln in css.splitlines() if "dashed" in ln], ["table:nth-of-type(2) td:nth-child(3)"])

# ---- 2. losses: empty pv/export == old formula ----
loss = load("packages/optional/deye_inverter_losses.yaml")["template"][0]["sensor"][0]
st = {"sensor.elfin_deye_grid_import_total": "3473.6", "sensor.elfin_deye_battery_charge_total": "1987.8",
      "sensor.elfin_deye_battery_discharge_total": "1784.7", "sensor.elfin_deye_load_total": "3125.0"}
old = round(3473.6 + 1784.7 - 1987.8 - 3125.0, 1)
check("losses state (no pv/export) == old formula", Env(st, d).r(loss["state"]), str(old))
check("losses available", Env(st, d).r(loss["availability"]), "True")
check("losses unavailable on 0 read", Env({**st, "sensor.elfin_deye_load_total": "0"}, d).r(loss["availability"]), "False")
with_pv = loss["state"].replace("{% set pv_entity = '' %}", "{% set pv_entity = 'sensor.pv_total' %}")
check("losses with pv adds pv", Env({**st, "sensor.pv_total": "100.0"}, d).r(with_pv), str(round(old + 100.0, 1)))

# ---- 3. grid charge bit 0 ----
tou = load("packages/deye_tou.yaml")["template"]
gc1 = [s for s in tou[1]["binary_sensor"] if s["unique_id"].endswith("slot_1")][0]
for raw, want in [("5", "True"), ("4", "False"), ("7", "True"), ("6", "False"), ("9", "True")]:
    check(f"grid charge raw {raw}", Env({"sensor.elfin_deye_tou_grid_charge_slot_1_raw": raw}, d).r(gc1["state"]), want)
check("grid charge unavailable",
      Env({"sensor.elfin_deye_tou_grid_charge_slot_1_raw": "unavailable"}, d).r(gc1["availability"]), "False")
gcs = [s for s in tou[0]["sensor"] if s["unique_id"] == "elfin_deye_tou_grid_charge_state"][0]


def mk(vals):
    return {f"sensor.elfin_deye_tou_grid_charge_slot_{i}_raw": v for i, v in enumerate(vals, 1)}


check("grid charge state all 5", Env(mk(["5"] * 6), d).r(gcs["state"]), "all_on")
check("grid charge state mixed", Env(mk(["5", "4", "5", "4", "5", "4"]), d).r(gcs["state"]), "mixed")
check("grid charge state all 4", Env(mk(["4"] * 6), d).r(gcs["state"]), "all_off")
check("grid charge state one missing", Env(mk(["5"] * 5 + ["unavailable"]), d).r(gcs["state"]), "not_verified")

# ---- 4. clock write: one now() ----
clk_seq = load("packages/deye_clock.yaml")["script"]["elfin_deye_sync_clock_once"]["sequence"]
clk = clk_seq[0]["variables"]["regs"]
t = dt.datetime(2026, 10, 6, 14, 59, 59)
check("clock regs at 14:59:59", Env({}, t).r(clk), str([26 * 256 + 10, 6 * 256 + 14, 59 * 256 + 59]))

# ---- 5. clock read-back verification incl. DST phantom +3600 ----
cond = [x for x in clk_seq if "if" in x][0]["if"][0]["value_template"]
for off, want in [("2", "True"), ("-9", "True"), ("3601", "True"), ("-3598", "True"),
                  ("304", "False"), ("3700", "False"), ("3500", "False"), ("unavailable", "False")]:
    check(f"clock verify offset {off}", Env({}, d).r(cond, offset_after=off), want)

# ---- 6. outage duration across restarts ----
go = load("packages/optional/deye_grid_outage.yaml")
trig = [b for b in go["template"] if "triggers" in b][0]


def last_duration(is_active, rec, off_at, on_at):
    stt = {"input_boolean.elfin_deye_grid_outage_active": "on" if is_active else "off"}
    att = {("input_datetime.elfin_deye_grid_outage_started", "timestamp"): rec.timestamp() if rec else None}
    e = Env(stt, on_at, att)
    trigger = types.SimpleNamespace(from_state=types.SimpleNamespace(last_changed=off_at),
                                    to_state=types.SimpleNamespace(last_changed=on_at))
    var = {"trigger": trigger}
    for k, tpl in trig["variables"].items():
        var[k] = native(e.r(tpl, **var))
    sen = trig["sensor"][0]
    return e.r(sen["state"], **var), {k: native(e.r(v, **var)) for k, v in sen["attributes"].items()}


def D(h, m, s=0):
    return dt.datetime(2026, 10, 8, h, m, s)


check("outage across restart 11:41-15:06 (restart 14:12)", last_duration(True, D(11, 41), D(14, 12, 30), D(15, 6))[0], "3h 25m")
check("normal 18 min outage", last_duration(True, D(19, 18, 10), D(19, 18, 10), D(19, 36, 10))[0], "0h 18m")
check("short dip, no active flag", last_duration(False, D(9, 0), D(12, 0), D(12, 1, 30))[0], "0h 01m")
check("very short dip, 194 held 0 for ~65 s", last_duration(True, D(17, 18, 10), D(17, 18, 10), D(17, 19, 15))[0], "0h 01m")
check("recorded start later than off -> ignored", last_duration(True, D(13, 0), D(12, 0), D(12, 30))[0], "0h 30m")
_, attrs = last_duration(True, D(11, 41), D(14, 12, 30), D(15, 6))
check("started_at attribute = recorded start", attrs["started_at"], int(D(11, 41).timestamp()))

boot = [a for a in go["automation"] if a["id"] == "elfin_deye_startup_bootstrap"][0]
then = [x for x in boot["actions"] if "if" in x][0]["then"]
bvars = then[0]["variables"]
bcond = [x for x in then if x.get("condition") == "template"][0]["value_template"]
bmsg = [x for x in then if x.get("action") == "script.elfin_deye_notify_all"][0]["data"]["message"]


def bootstrap(start, sensor_started_at, boot_at, now):
    stt = {"sensor.elfin_deye_last_grid_outage_duration": "3h 25m", "sensor.elfin_deye_battery_soc": "80"}
    att = {("input_datetime.elfin_deye_grid_outage_started", "timestamp"): start.timestamp(),
           ("sensor.elfin_deye_last_grid_outage_duration", "started_at"): sensor_started_at}
    e = Env(stt, now, att)
    var = {"v_boot": int(boot_at.timestamp())}
    for k, tpl in bvars.items():
        var[k] = native(e.r(tpl, **var))
    return e.r(bcond, **var), " ".join(e.r(bmsg, **var).split())


c, m = bootstrap(D(11, 41), int(D(11, 41).timestamp()), D(14, 12), D(15, 10))
check("bootstrap reports outage begun before restart", c, "True")
check("bootstrap exact duration when sensor matches", "Outage duration: 3h 25m" in m, True)
c, m = bootstrap(D(11, 41), 0, D(14, 12), D(15, 10))
check("bootstrap approximate when sensor stale", "at most 3h 29m" in m, True)
c, m = bootstrap(D(14, 12, 40), 0, D(14, 12), D(14, 14))
check("bootstrap silent for outage inside grace", c, "False")
print("sample bootstrap message:", bootstrap(D(11, 41), 0, D(14, 12), D(15, 10))[1])

sys.exit(1 if fails else 0)
