"""Random Kundur-family grids for the RSI loop's grid pool: one training grid X and one scoring grid Y per draw.

    python test_cases/sample_random_grids.py --device REGF1 --seed 7          # print the two specs of one draw

Every draw is a pair of independent grids for the same device: X is recorded the way grid A is (12 runs at three
operating points: ambient, staged voltage-reference steps, a generator trip, a load step, a fault, a line trip;
two validation runs; two held-out runs) and is what the solver identifies from; Y is scored the way grid B is
(three held-out runs: a voltage-reference step, a load step, a line trip). Both are the same ten-bus network that
grids A, B and M are built from, varied within these ranges (decided Nov 17, 2026):

  device slot     the unit takes generator 2's, 3's or 4's place (generator 1 is the slack and stays)
  circuits out    each parallel corridor (5-6, 6-7, 7-8, 8-9, 9-10) has one circuit out with probability 1/4,
                  at most one corridor per grid (op3 and the trips add one more), so every corridor keeps a
                  circuit in service
  loads           bus 7 and bus 8 loads at grid A's values x U(0.8, 1.2); one more load of U(0.2, 3.0) pu
                  (20 to 300 MW) at bus 9 or 10
  dispatch        the unit at U(0.45, 0.7) of its 900 MVA rating; the other two non-slack generators at grid A's
                  dispatch x U(0.85, 1.15); the unit's voltage schedule U(0.99, 1.02), the generators' 1.00 pu as in
                  grid A; a draw whose slack generator would land outside 250 to 800 MW is drawn again
  events          which load steps, which circuit trips (only from a corridor with two or more in service), where
                  the fault is (buses 5 to 10), and which generator trips: never the unit's slot, and one small
                  enough that the unit's share of it keeps the unit under 90% of its rating (unit P + 0.45 x
                  tripped P <= 810 MW; on grid A the unit picked up about 35% of the 400 MW trip). With the unit in
                  generator 2's slot, generator 3 or 4 is re-dispatched to 350 to 500 MW to be the one that trips

Sampler v1 (Nov 17) drew every generator's voltage schedule independently in U(0.99, 1.03), the unit up to 0.8 of its
rating, up to two corridors out and any generator trip. 23 of its first 25 draws were thrown out: the unit's Q
limiter bound in 37 runs (mismatched schedules left it carrying 200 to 400 Mvar before any event), its P limiter in
8 (700 MW trips), and 27 simulations failed. v2 is the fix.

A draw is a pure function of (device, seed). build_grid_pool.py simulates it, throws out draws where the power flow
or a simulation fails or a limiter binds, and keeps the rest. The unit's parameters are the ones in its training
grid's spec (grid A for REGF1, A2 for REGF2), so only the network around it changes.
"""
import argparse
import copy
import json
from pathlib import Path

import numpy as np

TEST_CASES_DIR = Path(__file__).resolve().parent
GRID_SPECS_DIR = TEST_CASES_DIR / "grid_specs"

CORRIDORS = {"5-6": ["Line_0", "Line_1"], "6-7": ["Line_2", "Line_3"], "7-8": ["Line_4", "Line_5", "Line_6"],
             "8-9": ["Line_7", "Line_8"], "9-10": ["Line_9", "Line_10"]}
CORRIDOR_OUT_PROBABILITY, MAX_CORRIDORS_OUT = 0.25, 1
BASE_DISPATCH = {2: 4.0, 3: 7.0, 4: 7.0}               # pu on 100 MVA: grid A's op1 (area 1 re-dispatched)
BASE_LOADS = {"PQ_0": 8.59, "PQ_1": 14.25}             # bus 7, bus 8: grid A's op1
LOAD_BUS = {"PQ_0": 7, "PQ_1": 8, "PQ_2": 10, "PQ_3": 9}   # as build_test_grids.py names them
EXTRA_LOAD_AT_BUS = {9: "PQ_3", 10: "PQ_2"}
DEVICE_SLOTS = (2, 3, 4)
DEVICE_RATING_PU = 9.0                                 # 900 MVA on the 100 MVA system base
DEVICE_SHARE_RANGE = (0.45, 0.7)
OTHER_DISPATCH_FACTOR, LOAD_FACTOR, EXTRA_LOAD_PU = (0.85, 1.15), (0.8, 1.2), (0.2, 3.0)
VOLTAGE_SCHEDULE = (0.99, 1.02)                    # the unit's; the generators stay at 1.00 pu
TRIP_SHARE, TRIP_HEADROOM_PU, SMALL_TRIP_PU = 0.45, 8.1, (3.5, 5.0)
SLACK_RANGE_PU, ESTIMATED_LOSSES_PU = (2.5, 8.0), 0.4
TRAINING_GRID_OF_DEVICE = {"REGF1": "A", "REGF2": "A2"}
FAULT_BUSES = (5, 6, 7, 8, 9, 10)
SAMPLER_VERSION = 2                                    # bump when a change would make a seed give a different grid


def device_under_test(device):
    """The unit's model and parameters, from its training grid's spec."""
    with open(GRID_SPECS_DIR / f"grid_{TRAINING_GRID_OF_DEVICE[device]}.json") as file:
        return json.load(file)["device_under_test"]


# ---- the network and its operating point --------------------------------------------------------------------------
def _sample_network(rng):
    """(device slot, extra load (idx, bus), {corridor: circuit out})."""
    slot = int(rng.choice(DEVICE_SLOTS))
    bus = int(rng.choice(sorted(EXTRA_LOAD_AT_BUS)))
    out = {}
    for corridor, circuits in CORRIDORS.items():
        if rng.random() < CORRIDOR_OUT_PROBABILITY:
            out[corridor] = str(rng.choice(circuits))
    while len(out) > MAX_CORRIDORS_OUT:
        out.pop(str(rng.choice(sorted(out))))
    return slot, (EXTRA_LOAD_AT_BUS[bus], bus), out


def slack_estimate(operating_point):
    """Roughly what the slack generator supplies (pu): load plus losses minus every other generator."""
    load = sum(values["p0"] for values in operating_point["pq"].values())
    generation = sum(values["p0"] for values in operating_point["pv"].values())
    return load + ESTIMATED_LOSSES_PU - generation


def _sample_operating_point(rng, slot, extra_load, lines_out, trip=None):
    """trip: the generator that will trip in this operating point, or None. Its dispatch is kept small enough that
    the unit's share of the loss leaves it under 90% of its rating (re-dispatched to 350 to 500 MW if it is one of
    the 700 MW machines)."""
    for _ in range(1000):
        pv = {}
        for machine in DEVICE_SLOTS:
            if machine == slot:
                p0 = rng.uniform(*DEVICE_SHARE_RANGE) * DEVICE_RATING_PU
            elif machine == trip and BASE_DISPATCH[machine] > SMALL_TRIP_PU[1]:
                p0 = rng.uniform(*SMALL_TRIP_PU)
            else:
                p0 = BASE_DISPATCH[machine] * rng.uniform(*OTHER_DISPATCH_FACTOR)
            v0 = rng.uniform(*VOLTAGE_SCHEDULE) if machine == slot else 1.0
            pv[str(machine)] = {"p0": round(float(p0), 4), "v0": round(float(v0), 4)}
        if trip is not None and pv[str(slot)]["p0"] + TRIP_SHARE * pv[str(trip)]["p0"] > TRIP_HEADROOM_PU:
            continue
        pq = {load: {"p0": round(float(base * rng.uniform(*LOAD_FACTOR)), 4)} for load, base in BASE_LOADS.items()}
        pq[extra_load[0]] = {"p0": round(float(rng.uniform(*EXTRA_LOAD_PU)), 4)}
        point = {"pv": pv, "pq": pq, "lines_out": sorted(lines_out)}
        if SLACK_RANGE_PU[0] <= slack_estimate(point) <= SLACK_RANGE_PU[1]:
            return point
    raise RuntimeError("no dispatch within the slack range in 1000 tries")


def trippable_circuits(lines_out):
    """Circuits whose corridor would keep at least one circuit in service after they open."""
    return [circuit for circuits in CORRIDORS.values() if sum(c not in lines_out for c in circuits) >= 2
            for circuit in circuits if circuit not in lines_out]


def _corridor_of(circuit):
    return next(name for name, circuits in CORRIDORS.items() if circuit in circuits)


def _circuits_out_by_corridor(lines_out):
    counts = {}
    for circuit in lines_out:
        counts[_corridor_of(circuit)] = counts.get(_corridor_of(circuit), 0) + 1
    return counts


# ---- events ------------------------------------------------------------------------------------------------------
def _ambient(rng, loads, sigma, t1):
    return {"kind": "ambient", "loads": loads, "sigma": sigma, "tau": 5.0, "dt": 0.5,
            "seed": int(rng.integers(1, 2**31 - 1)), "t1": t1}


def _vref_steps(times, amounts):
    return [{"kind": "vref_step", "t": float(t), "amount": float(a)} for t, a in zip(times, amounts)]


def _load_step(rng, loads, t, factors):
    factor = float(rng.uniform(*factors[int(rng.integers(len(factors)))]))
    return {"kind": "load_scale", "t": t, "load": str(rng.choice(loads)), "p": round(factor, 3), "q": round(factor, 3)}


# ---- the two grids of a draw ---------------------------------------------------------------------------------------
def _case(name, description, slot, extra_load, operating_points, runs):
    idx, bus = extra_load
    return {"format": "kundur_family_v1", "name": name, "description": description, "device": {"syn": slot},
            "network": {"extra_loads": [{"idx": idx, "bus": bus, "p0": operating_points[next(iter(operating_points))]["pq"][idx]["p0"],
                                         "q0": 0.0}]},
            "operating_points": operating_points, "runs": runs}


def _describe_point(point, slot, extra_bus):
    unit = point["pv"][str(slot)]
    others = ", ".join(f"bus {machine} {point['pv'][str(machine)]['p0'] * 100:.0f} MW" for machine in DEVICE_SLOTS
                       if machine != slot)
    loads = ", ".join(f"bus {LOAD_BUS[load]} {values['p0'] * 100:.0f} MW" for load, values in sorted(point["pq"].items()))
    out = point["lines_out"]
    outages = ("all circuits in service" if not out else
               "out of service: " + ", ".join(f"one circuit {_corridor_of(c)}" for c in out))
    return (f"Unit at bus {slot} dispatched near {unit['p0'] * 100:.0f} MW, voltage schedule {unit['v0']:.3f} pu. "
            f"Other generators: {others}; the generator at bus 1 balances. Loads: {loads}. Network: {outages}.")


def sample_pair(device, seed):
    """(X spec, Y spec, summary) of draw (device, seed): two grid specs in grid_specs/ format."""
    rng = np.random.default_rng([SAMPLER_VERSION, list(TRAINING_GRID_OF_DEVICE).index(device), int(seed)])
    unit = device_under_test(device)
    tag = f"{device.lower()}_{int(seed):04d}"

    # X: the training grid, three operating points like grid A's
    slot, extra_load, out = _sample_network(rng)
    lines_out = sorted(out.values())
    trip = 2 if slot != 2 else int(rng.choice([3, 4]))
    op1 = _sample_operating_point(rng, slot, extra_load, lines_out, trip=trip)
    op2 = copy.deepcopy(op1)
    old_p, new_p = op1["pv"][str(slot)]["p0"], round(float(rng.uniform(*DEVICE_SHARE_RANGE) * DEVICE_RATING_PU), 4)
    balancing = int(rng.choice([machine for machine in DEVICE_SLOTS if machine != slot]))
    op2["pv"][str(slot)]["p0"] = new_p
    op2["pv"][str(balancing)]["p0"] = round(float(np.clip(op1["pv"][str(balancing)]["p0"] + old_p - new_p, 1.0, 8.5)), 4)
    op2["pv"][str(slot)]["v0"] = round(min(op1["pv"][str(slot)]["v0"] + 0.01, 1.03), 4)
    op3 = copy.deepcopy(op1)
    op3["lines_out"] = sorted(lines_out + [str(rng.choice(trippable_circuits(lines_out)))])
    op3["pq"]["PQ_1"]["p0"] = round(op3["pq"]["PQ_1"]["p0"] + 1.0, 4)
    loads = sorted(op1["pq"])
    up_or_down = [(0.88, 0.94), (1.06, 1.12)]
    runs = {
        "X_amb_op1": {"split": "train", "op": "op1", "tf": 60.0, "events": [_ambient(rng, loads, 0.01, 60.0)]},
        "X_amb_op2": {"split": "train", "op": "op2", "tf": 60.0, "events": [_ambient(rng, loads, 0.01, 60.0)]},
        "X_vref_op1": {"split": "train", "op": "op1", "tf": 60.0, "events": [_ambient(rng, loads, 0.003, 60.0)]
                       + _vref_steps((5.0, 20.0, 35.0, 50.0), (0.02, -0.02, -0.02, 0.02))},
        "X_vref_op3": {"split": "train", "op": "op3", "tf": 45.0, "events": [_ambient(rng, loads, 0.003, 45.0)]
                       + _vref_steps((5.0, 15.0, 25.0, 35.0), (0.01, -0.01, -0.01, 0.01))},
        "X_gentrip_op1": {"split": "train", "op": "op1", "tf": 40.0, "events": [
            _ambient(rng, loads, 0.003, 40.0), {"kind": "gen_trip", "t": 5.0, "syn": trip}]},
        "X_load_op2": {"split": "train", "op": "op2", "tf": 40.0, "events": [
            _ambient(rng, loads, 0.003, 40.0), _load_step(rng, loads, 5.0, up_or_down)]},
        "X_fault_op1": {"split": "train", "op": "op1", "tf": 30.0, "events": [
            _ambient(rng, loads, 0.003, 30.0),
            {"kind": "fault", "t": 5.0, "bus": int(rng.choice(FAULT_BUSES)), "dur": 0.1, "xf": 0.1, "rf": 0.0}]},
        "X_line_op3": {"split": "train", "op": "op3", "tf": 30.0, "events": [
            _ambient(rng, loads, 0.003, 30.0),
            {"kind": "line_trip", "t": 5.0, "line": str(rng.choice(trippable_circuits(op3["lines_out"])))}]},
        "X_val_load_op1": {"split": "val", "op": "op1", "tf": 30.0, "events": [
            _ambient(rng, loads, 0.003, 30.0), _load_step(rng, loads, 5.0, up_or_down)]},
        "X_val_vref_op2": {"split": "val", "op": "op2", "tf": 30.0, "events": [_ambient(rng, loads, 0.003, 30.0)]
                           + _vref_steps((5.0, 20.0), (0.015, -0.015))},
        "X_test_line_op1": {"split": "holdout", "op": "op1", "tf": 20.0, "events": [
            {"kind": "line_trip", "t": 2.0, "line": str(rng.choice(trippable_circuits(lines_out)))}]},
        "X_test_vref_op1": {"split": "holdout", "op": "op1", "tf": 20.0, "events": _vref_steps((2.0, 12.0), (-0.015, 0.015))},
    }
    x_case = _case(f"grid_X_{tag}", f"random training grid {tag} (sampler v{SAMPLER_VERSION}): unit in generator "
                   f"{slot}'s slot", slot, extra_load, {"op1": op1, "op2": op2, "op3": op3}, runs)
    log = {"op1": _describe_point(op1, slot, extra_load[1]),
           "op2": _describe_point(op2, slot, extra_load[1]) + f" (Re-dispatched from op1: the generator at bus "
                                                              f"{balancing} picks up the difference.)",
           "op3": _describe_point(op3, slot, extra_load[1]) + " (op1 with one more circuit out for maintenance and "
                                                              "the bus-8 load about 100 MW heavier.)"}
    x_spec = {"purpose": f"Random training grid of draw {tag}: what the solver identifies the unit from.",
              "case": x_case, "device_under_test": unit, "operating_conditions_log": log,
              "design_notes": [f"Drawn by test_cases/sample_random_grids.py, sampler v{SAMPLER_VERSION}, device "
                               f"{device}, seed {seed}."]}

    # Y: the scoring grid, an independent draw with one operating point like grid B's
    y_slot, y_extra, y_out = _sample_network(rng)
    y_lines_out = sorted(y_out.values())
    op_y = _sample_operating_point(rng, y_slot, y_extra, y_lines_out)
    y_loads = sorted(op_y["pq"])
    amount = float(rng.uniform(0.015, 0.025)) * (1 if rng.random() < 0.5 else -1)
    y_runs = {
        "Y_vref": {"split": "holdout", "op": "opY", "tf": 25.0, "events": _vref_steps((2.0, 14.0), (round(amount, 4), -round(amount, 4)))},
        "Y_load": {"split": "holdout", "op": "opY", "tf": 25.0,
                   "events": [_load_step(rng, y_loads, 2.0, [(0.6, 0.8), (1.2, 1.5)])]},
        "Y_line": {"split": "holdout", "op": "opY", "tf": 25.0,
                   "events": [{"kind": "line_trip", "t": 2.0, "line": str(rng.choice(trippable_circuits(y_lines_out)))}]},
    }
    y_case = _case(f"grid_Y_{tag}", f"random scoring grid {tag} (sampler v{SAMPLER_VERSION}): unit in generator "
                   f"{y_slot}'s slot", y_slot, y_extra, {"opY": op_y}, y_runs)
    y_spec = {"purpose": f"Random scoring grid of draw {tag}: held-out runs only, never shown to the solver or the updater.",
              "case": y_case, "device_under_test": unit,
              "design_notes": [f"Drawn by test_cases/sample_random_grids.py, sampler v{SAMPLER_VERSION}, device "
                               f"{device}, seed {seed}."]}

    summary = {"device": device, "seed": int(seed), "sampler_version": SAMPLER_VERSION,
               "X": {"slot": slot, "lines_out": lines_out, "extra_load_bus": extra_load[1],
                     "unit_MW": round(op1["pv"][str(slot)]["p0"] * 100), "slack_estimate_MW": round(slack_estimate(op1) * 100)},
               "Y": {"slot": y_slot, "lines_out": y_lines_out, "extra_load_bus": y_extra[1],
                     "unit_MW": round(op_y["pv"][str(y_slot)]["p0"] * 100), "slack_estimate_MW": round(slack_estimate(op_y) * 100)}}
    return x_spec, y_spec, summary


def diagram_labels(x_spec):
    """draw_grid_diagrams.draw_grid's labels for a random training grid (what the solver sees)."""
    case = x_spec["case"]
    slot, ops = case["device"]["syn"], case["operating_points"]
    op1, op2, op3 = ops["op1"], ops["op2"], ops["op3"]
    labels = {f"g{machine}": f"{op1['pv'][str(machine)]['p0'] * 100:.0f} MW" for machine in DEVICE_SLOTS if machine != slot}
    unit = op1["pv"][str(slot)]
    labels["device"] = f"900 MVA\n{unit['p0'] * 100:.0f} MW ({op2['pv'][str(slot)]['p0'] * 100:.0f} MW at op2)"
    loads = {}
    for load, values in sorted(op1["pq"].items()):
        text = f"L{LOAD_BUS[load]}  {values['p0'] * 100:.0f} MW"
        if load == "PQ_1":
            text += f"\n({op3['pq']['PQ_1']['p0'] * 100:.0f} MW at op3)"
        loads[LOAD_BUS[load]] = text
    extra_out = [c for c in op3["lines_out"] if c not in op1["lines_out"]]
    notes = ["Ten-bus, two-area system; transformers between buses 1-5, 2-6, 3-9 and 4-10; dashed circuits are out of "
             "service. Operating points (see runs.json):",
             f"op1 as drawn, voltage schedule {unit['v0']:.3f} pu.  op2: unit at {op2['pv'][str(slot)]['p0'] * 100:.0f} MW, "
             f"schedule {op2['pv'][str(slot)]['v0']:.3f} pu.  op3: one more {_corridor_of(extra_out[0])} circuit out, "
             f"L8 +100 MW."]
    return dict(labels, device_slot=slot, loads=loads, notes=notes, tie_label=None,
                circuits_out=_circuits_out_by_corridor(op1["lines_out"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--device", default="REGF1", choices=sorted(TRAINING_GRID_OF_DEVICE))
    parser.add_argument("--seed", type=int, default=0)
    options = parser.parse_args()
    x_spec, y_spec, summary = sample_pair(options.device, options.seed)
    print(json.dumps({"summary": summary, "X": x_spec, "Y": y_spec}, indent=1))


if __name__ == "__main__":
    main()
