"""Kundur-family grids rebuilt from a case spec (holdout/case.json). Trusted side only.

One builder serves every grid derived from ANDES's kundur_full case: the spec says which GENROU slot the
device takes, how the network and dispatch differ, and what happens in each run. The test-case builder
(test_cases/build_test_grids.py) and the scorer both call build_system(), so a held-out run is replayed with
exactly the events that produced its recording.

Case spec layout
  device           {"syn": 3}   GENROU (with its TGOV1 and EXDC2) replaced by the device: same bus,
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
import numpy as np
import pandas as pd

# the device's idx in the ANDES system (never shown to the agents)
DEVICE_SLOT_IDX = "GFM_1"
# the ANDES variable a staged voltage-reference test alters, per device model; a submission's is c_Vset
VOLTAGE_SETPOINT_VARIABLE = {"REGF1": "vref"}
SUBMISSION_SETPOINT_VARIABLE = "c_Vset"


def ambient_load_factors(event):
    """Piecewise-constant P and Q multipliers per load: {load: (times, P factors, Q factors)}."""
    rng = np.random.default_rng(int(event["seed"]))
    step, correlation_time, sigma = float(event["dt"]), float(event["tau"]), float(event["sigma"])
    times = np.arange(float(event.get("t0", step)), float(event["t1"]) - 1e-9, step)
    decay = np.exp(-step / correlation_time)
    factors = {}
    for load in event["loads"]:
        sequences = []
        for _ in range(2):                      # P, then Q
            x, sequence = 0.0, []
            for _ in times:
                x = decay * x + sigma * np.sqrt(1 - decay * decay) * rng.standard_normal()
                sequence.append(1.0 + x)
            sequences.append(np.array(sequence))
        factors[load] = (times, sequences[0], sequences[1])
    return factors


def _add_events(system, device_model, events):
    for event in events:
        kind = event["kind"]
        if kind == "vref_step":
            system.add("Alter", dict(model=device_model, dev=DEVICE_SLOT_IDX,
                                     src=VOLTAGE_SETPOINT_VARIABLE.get(device_model, SUBMISSION_SETPOINT_VARIABLE),
                                     attr="v", method="+", amount=float(event["amount"]), t=float(event["t"])))
        elif kind == "load_scale":
            for source, factor in (("Req", event.get("p", 1.0)), ("Xeq", event.get("q", 1.0))):
                if factor != 1.0:
                    system.add("Alter", dict(model="PQ", dev=event["load"], src=source, attr="v", method="*",
                                             amount=float(factor), t=float(event["t"])))
        elif kind == "line_trip":
            system.add("Toggle", dict(model="Line", dev=event["line"], t=float(event["t"])))
        elif kind == "gen_trip":
            system.add("Toggle", dict(model="GENROU", dev=int(event["syn"]), t=float(event["t"])))
        elif kind == "fault":
            system.add("Fault", dict(bus=int(event["bus"]), tf=float(event["t"]), tc=float(event["t"]) + float(event["dur"]),
                                     xf=float(event.get("xf", 0.1)), rf=float(event.get("rf", 0.0))))
        elif kind == "ambient":
            for load, (times, p_factors, q_factors) in ambient_load_factors(event).items():
                previous_p = previous_q = 1.0
                for time, p_factor, q_factor in zip(times, p_factors, q_factors):
                    system.add("Alter", dict(model="PQ", dev=load, src="Req", attr="v", method="*",
                                             amount=float(p_factor / previous_p), t=float(time)))
                    system.add("Alter", dict(model="PQ", dev=load, src="Xeq", attr="v", method="*",
                                             amount=float(q_factor / previous_q), t=float(time)))
                    previous_p, previous_q = p_factor, q_factor
        else:
            raise ValueError(f"unknown event kind {kind}")


def build_system(device_model, device_params, run_name, pycode_path=None, case_spec=None):
    """An ANDES System with device_model in the slot, at run_name's operating point and with its events,
    power flow solved. device_params are the device's ANDES parameters."""
    import andes                                    # imported here so the helpers above work without ANDES
    run = case_spec["runs"][run_name]
    operating_point = case_spec["operating_points"][run["op"]]
    network = case_spec.get("network", {})
    replaced_machine = int(case_spec["device"]["syn"])
    sheets = pd.read_excel(andes.get_case("kundur/kundur_full.xlsx"), sheet_name=None, engine="openpyxl")
    slot = sheets["GENROU"].set_index("idx").loc[replaced_machine]
    # rows are dropped rather than set to u = 0: a disabled TGOV1 keeps a lead-lag init residual
    sheets["GENROU"] = sheets["GENROU"][sheets["GENROU"].idx != replaced_machine]
    for name in ("TGOV1", "EXDC2"):
        sheets[name] = sheets[name][sheets[name].syn != replaced_machine]
    sheets.pop("Toggler", None)                     # the case file ships a Line_8 trip at 2 s

    pv_changes = {int(gen): values for gen, values in operating_point.get("pv", {}).items()}
    for column in ("p0", "v0"):
        sheets["PV"][column] = [pv_changes.get(idx, {}).get(column, value)
                                for idx, value in zip(sheets["PV"].idx, sheets["PV"][column])]
    pq_changes = operating_point.get("pq", {})
    for column in ("p0", "q0"):
        sheets["PQ"][column] = [pq_changes.get(idx, {}).get(column, value)
                                for idx, value in zip(sheets["PQ"].idx, sheets["PQ"][column])]
    sheets["Line"].loc[sheets["Line"].idx.isin(operating_point.get("lines_out", [])), "u"] = 0

    system = andes.System(default_config=True, no_output=True, pycode_path=pycode_path)
    for name, table in sheets.items():
        for row in table.dropna(how="all").to_dict(orient="records"):
            system.add(name, row)
    system.add(device_model, dict(idx=DEVICE_SLOT_IDX, name=DEVICE_SLOT_IDX, bus=slot.bus, gen=slot.gen, Sn=slot.Sn,
                                  gammap=1.0, gammaq=1.0) | dict(device_params))
    for load in network.get("extra_loads", []):
        load = dict(load) | pq_changes.get(load["idx"], {})
        system.add("PQ", dict(load, name=load["idx"], Vn=system.Bus.get("Vn", load["bus"])))
    _add_events(system, device_model, run.get("events", []))
    system.setup()
    if not system.PFlow.run():
        raise RuntimeError("power flow failed")
    return system


def voltage_setpoint_series(case_spec, run_name, times, schedule):
    """The device voltage setpoint over time, as the operator's control log shows it."""
    setpoint = np.full(len(times), float(schedule))
    for event in case_spec["runs"][run_name].get("events", []):
        if event["kind"] == "vref_step":
            setpoint[times >= float(event["t"]) - 1e-12] += float(event["amount"])
    return setpoint


def switching_times(case_spec, run_name):
    """Instants where the network or a setpoint changes (for plots)."""
    times = []
    for event in case_spec["runs"][run_name].get("events", []):
        if event["kind"] == "fault":
            times += [float(event["t"]), float(event["t"]) + float(event["dur"])]
        elif event["kind"] != "ambient":
            times.append(float(event["t"]))
    return sorted(times)
