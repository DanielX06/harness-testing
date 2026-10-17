"""Kundur-family grids built from a case spec (holdout/case.json). Trusted side only.

One builder serves every grid derived from ANDES's kundur_full case: the spec says which
GENROU slot the device takes, how the network and dispatch differ, and what happens in each
run. The data generator (test_cases/build_cases.py) and the scorer both call build(), so a
held-out run is replayed with exactly the events that produced its recording.

Spec layout
  device           {"syn": 3}   GENROU (with its TGOV1/EXDC2) replaced by the device, same bus,
                                StaticGen and MVA rating
  network          permanent changes: extra_loads [...]
  operating_points {op: {"pv": {gen: {"p0":..,"v0":..}}, "pq": {load: {"p0":..,"q0":..}},
                         "lines_out": [...]}}
  runs             {run: {"split", "op", "tf", "events": [...]}}

Event kinds (times in s)
  vref_step  {"t", "amount"}               device voltage setpoint += amount (pu)
  load_scale {"t", "load", "p", "q"}       constant-impedance P and Q of a load times p and q
  line_trip  {"t", "line"}                 line opened (ANDES Toggle)
  gen_trip   {"t", "syn"}                  GENROU opened
  fault      {"t", "bus", "dur", "xf", "rf"}  three-phase fault, cleared after dur
  ambient    {"loads", "sigma", "tau", "dt", "seed", "t0", "t1"}
             each load's P and Q follow independent Ornstein-Uhlenbeck processes
             (std sigma, correlation time tau), held for dt between updates
"""
import andes
import numpy as np
import pandas as pd

SETPOINT_SRC = {"REGF1": "vref"}   # submissions: c_Vset
DEVICE_IDX = "GFM_1"


def ambient_factors(ev):
    """Piecewise-constant P and Q multipliers per load: {load: (times, p_factor, q_factor)}."""
    rng = np.random.default_rng(int(ev["seed"]))
    dt, tau, sig = float(ev["dt"]), float(ev["tau"]), float(ev["sigma"])
    times = np.arange(float(ev.get("t0", dt)), float(ev["t1"]) - 1e-9, dt)
    a = np.exp(-dt / tau)
    out = {}
    for load in ev["loads"]:
        xs = []
        for _ in range(2):                      # P then Q
            x, seq = 0.0, []
            for _ in times:
                x = a * x + sig * np.sqrt(1 - a * a) * rng.standard_normal()
                seq.append(1.0 + x)
            xs.append(np.array(seq))
        out[load] = (times, xs[0], xs[1])
    return out


def _add_events(ss, device, events):
    for ev in events:
        k = ev["kind"]
        if k == "vref_step":
            ss.add("Alter", dict(model=device, dev=DEVICE_IDX, src=SETPOINT_SRC.get(device, "c_Vset"),
                                 attr="v", method="+", amount=float(ev["amount"]), t=float(ev["t"])))
        elif k == "load_scale":
            for src, f in (("Req", ev.get("p", 1.0)), ("Xeq", ev.get("q", 1.0))):
                if f != 1.0:
                    ss.add("Alter", dict(model="PQ", dev=ev["load"], src=src, attr="v", method="*",
                                         amount=float(f), t=float(ev["t"])))
        elif k == "line_trip":
            ss.add("Toggle", dict(model="Line", dev=ev["line"], t=float(ev["t"])))
        elif k == "gen_trip":
            ss.add("Toggle", dict(model="GENROU", dev=int(ev["syn"]), t=float(ev["t"])))
        elif k == "fault":
            ss.add("Fault", dict(bus=int(ev["bus"]), tf=float(ev["t"]), tc=float(ev["t"]) + float(ev["dur"]),
                                 xf=float(ev.get("xf", 0.1)), rf=float(ev.get("rf", 0.0))))
        elif k == "ambient":
            for load, (times, fp, fq) in ambient_factors(ev).items():
                prev_p = prev_q = 1.0
                for t, p, q in zip(times, fp, fq):
                    ss.add("Alter", dict(model="PQ", dev=load, src="Req", attr="v", method="*",
                                         amount=float(p / prev_p), t=float(t)))
                    ss.add("Alter", dict(model="PQ", dev=load, src="Xeq", attr="v", method="*",
                                         amount=float(q / prev_q), t=float(t)))
                    prev_p, prev_q = p, q
        else:
            raise ValueError(f"unknown event kind {k}")


def build(device, dev_params, run, pycode_path=None, spec=None):
    """ANDES System with `device` in the slot, run `run`'s operating point and events, power flow
    solved. dev_params are the device's ANDES parameters."""
    r = spec["runs"][run]
    op = spec["operating_points"][r["op"]]
    net = spec.get("network", {})
    syn = int(spec["device"]["syn"])
    sheets = pd.read_excel(andes.get_case("kundur/kundur_full.xlsx"), sheet_name=None, engine="openpyxl")
    slot = sheets["GENROU"].set_index("idx").loc[syn]
    # rows dropped rather than u=0: a disabled TGOV1 keeps a lead-lag init residual
    sheets["GENROU"] = sheets["GENROU"][sheets["GENROU"].idx != syn]
    for name in ("TGOV1", "EXDC2"):
        sheets[name] = sheets[name][sheets[name].syn != syn]
    sheets.pop("Toggler", None)                       # the case file ships a Line_8 trip at 2 s

    pv = {int(k): v for k, v in op.get("pv", {}).items()}
    for col in ("p0", "v0"):
        sheets["PV"][col] = [pv.get(i, {}).get(col, x) for i, x in zip(sheets["PV"].idx, sheets["PV"][col])]
    pq = op.get("pq", {})
    for col in ("p0", "q0"):
        sheets["PQ"][col] = [pq.get(i, {}).get(col, x) for i, x in zip(sheets["PQ"].idx, sheets["PQ"][col])]
    sheets["Line"].loc[sheets["Line"].idx.isin(op.get("lines_out", [])), "u"] = 0

    ss = andes.System(default_config=True, no_output=True, pycode_path=pycode_path)
    for name, df in sheets.items():
        for row in df.dropna(how="all").to_dict(orient="records"):
            ss.add(name, row)
    ss.add(device, dict(idx=DEVICE_IDX, name=DEVICE_IDX, bus=slot.bus, gen=slot.gen, Sn=slot.Sn,
                        gammap=1.0, gammaq=1.0) | dict(dev_params))
    for ld in net.get("extra_loads", []):
        ld = dict(ld) | pq.get(ld["idx"], {})
        ss.add("PQ", dict(ld, name=ld["idx"], Vn=ss.Bus.get("Vn", ld["bus"])))
    _add_events(ss, device, r.get("events", []))
    ss.setup()
    if not ss.PFlow.run():
        raise RuntimeError("power flow failed")
    return ss


def vset_series(spec, run, t, v0):
    """The device voltage setpoint over time, as an operator's log would show it."""
    v = np.full(len(t), float(v0))
    for ev in spec["runs"][run].get("events", []):
        if ev["kind"] == "vref_step":
            v[t >= float(ev["t"]) - 1e-12] += float(ev["amount"])
    return v


def switching_times(spec, run):
    """Instants where the network or a setpoint changes (for plots and README tables)."""
    out = []
    for ev in spec["runs"][run].get("events", []):
        if ev["kind"] == "fault":
            out += [float(ev["t"]), float(ev["t"]) + float(ev["dur"])]
        elif ev["kind"] != "ambient":
            out.append(float(ev["t"]))
    return sorted(out)
