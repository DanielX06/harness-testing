"""A menu of control structures for the device, built from blocks. Each choice of blocks plus parameter values
becomes a complete submission (the same JSON format the task asks for), in pu on the device rating.

    python tools/structure_menu.py list                         # the blocks you may choose and their parameters
    python tools/structure_menu.py build --pf A --qv B --voltage C [--inner D] [--params p.json] --out submission.json

Every structure has the same skeleton. The device holds an internal angle delta. Its voltage control works in
a frame aligned with delta:
    vd = V cos(delta - theta),   vq = -V sin(delta - theta)
and its injected power is
    P = vd*Id + vq*Iq,   Q = -vd*Iq + vq*Id
where Id, Iq are the device's currents in that frame. P and Q are measured through a first-order filter
(time constant Tf) into Pf and Qf. The blocks decide how delta moves (pf), what voltage magnitude the device
aims for (qv), how it turns that into current (voltage) and how fast the current follows (inner).

Parameters you leave out take the defaults that `list` prints. They are generic starting values, not fitted
ones. tools/fit_structure.py fits them.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OPTIONS_FILE = os.path.join(HERE, "menu_options.json")

# ---- the blocks ------------------------------------------------------------------------------------------
# Each block: a description, its parameters with default values, and a function that adds its states and defs.
# Every block sits between ">>> block" and "<<< block" lines, so a harness can carry a copy of this file with
# only its own blocks in it.
BLOCKS = {"pf": {}, "qv": {}, "voltage": {}, "inner": {}}


def register(slot, name, about, params, build, prepare=None):
    BLOCKS[slot][name] = {"about": about, "params": params, "build": build, "prepare": prepare}


# >>> block pf/droop
def _pf_droop(defs, states, delta_init):
    states["delta"] = {"rhs": "w0*m*(P0 - Pf)", "init": delta_init}


register("pf", "droop", "frequency droop on filtered power: d(delta)/dt = w0*m*(P0 - Pf)", {"m": 0.05}, _pf_droop)
# <<< block pf/droop

# >>> block pf/inertia
def _pf_inertia(defs, states, delta_init):
    states["w"] = {"rhs": "(P0 - Pf - D*w)/M", "init": "0"}
    states["delta"] = {"rhs": "w0*w", "init": delta_init}


register("pf", "inertia",
         "emulated inertia: M*d(w)/dt = P0 - Pf - D*w (w is the internal frequency deviation in pu), d(delta)/dt = w0*w",
         {"M": 6.0, "D": 20.0}, _pf_inertia)
# <<< block pf/inertia

# >>> block qv/droop
def _qv_droop(defs, states):
    defs["vr"] = "Vset + n*(Q0 - Qf)"


register("qv", "droop", "reactive droop: vr = Vset + n*(Q0 - Qf)", {"n": 0.05}, _qv_droop)
# <<< block qv/droop

# >>> block qv/none
def _qv_none(defs, states):
    defs["vr"] = "Vset"


register("qv", "none", "no reactive droop: vr = Vset", {}, _qv_none)
# <<< block qv/none

# >>> block voltage/pi_voltage_loop
def _voltage_pi_prepare(defs):
    return "theta0"


def _voltage_pi(defs, states, inner):
    states["xvd"] = {"rhs": "Kiv*(vr - vd)", "init": "P0/V0"}
    states["xvq"] = {"rhs": "Kiv*(0 - vq)", "init": "-Q0/V0"}
    defs["Idref"] = "Kpv*(vr - vd) + xvd"
    defs["Iqref"] = "Kpv*(0 - vq) + xvq"
    BLOCKS["inner"][inner]["build"](defs, states)


register("voltage", "pi_voltage_loop",
         "PI voltage loop in the internal frame: Id_ref = Kpv*(vr - vd) + xvd, Iq_ref = Kpv*(0 - vq) + xvq, with xvd, "
         "xvq integrating Kiv times the same errors; delta starts at theta0",
         {"Kpv": 1.0, "Kiv": 5.0}, _voltage_pi, prepare=_voltage_pi_prepare)
# <<< block voltage/pi_voltage_loop

# >>> block voltage/voltage_behind_reactance
def _voltage_behind_reactance_prepare(defs):
    e_real, e_imag = "(V0 + Xv*Q0/V0)", "(Xv*P0/V0)"
    defs["E0"] = f"sqrt({e_real}**2 + {e_imag}**2)"
    return f"theta0 + atan2({e_imag}, {e_real})"


def _voltage_behind_reactance(defs, states, inner):
    defs["Id"] = "-vq/Xv"
    defs["Iq"] = "-(E0 + vr - V0 - vd)/Xv"


register("voltage", "voltage_behind_reactance",
         "an internal voltage of magnitude E0 + (vr - V0) at angle delta behind reactance Xv: Id = -vq/Xv, "
         "Iq = -(E0 + vr - V0 - vd)/Xv; E0 and the starting delta come from the operating point",
         {"Xv": 0.2}, _voltage_behind_reactance, prepare=_voltage_behind_reactance_prepare)
# <<< block voltage/voltage_behind_reactance

# >>> block inner/ideal
def _inner_ideal(defs, states):
    defs["Id"] = "Idref"
    defs["Iq"] = "Iqref"


register("inner", "ideal", "currents follow their references at once: Id = Id_ref, Iq = Iq_ref", {}, _inner_ideal)
# <<< block inner/ideal

# >>> block inner/pi_current_loop
def _inner_pi_current_loop(defs, states):
    states["xid"] = {"rhs": "Kii*(Idref - Id)", "init": "0"}
    states["xiq"] = {"rhs": "Kii*(Iqref - Iq)", "init": "0"}
    states["ud"] = {"rhs": "(udref - ud)/Te", "init": "V0 + rf*P0/V0 + xf*Q0/V0"}
    states["uq"] = {"rhs": "(uqref - uq)/Te", "init": "-rf*Q0/V0 + xf*P0/V0"}
    defs["det"] = "rf**2 + xf**2"
    defs["Id"] = "(rf*(ud - vd) + xf*(uq - vq))/det"
    defs["Iq"] = "(-xf*(ud - vd) + rf*(uq - vq))/det"
    defs["udref"] = "Kpi*(Idref - Id) + xid + vd + rf*Id - xf*Iq"
    defs["uqref"] = "Kpi*(Iqref - Iq) + xiq + vq + rf*Iq + xf*Id"


register("inner", "pi_current_loop",
         "PI current loop driving a converter voltage (ud, uq) through a lag Te and a filter reactance xf (resistance "
         "rf): Id = (rf*(ud - vd) + xf*(uq - vq))/(rf^2 + xf^2), Iq = (-xf*(ud - vd) + rf*(uq - vq))/(rf^2 + xf^2); "
         "ud_ref = Kpi*(Id_ref - Id) + xid + vd + rf*Id - xf*Iq, uq_ref = Kpi*(Iq_ref - Iq) + xiq + vq + rf*Iq + xf*Id, "
         "with xid, xiq integrating Kii times the current errors",
         {"Kpi": 1.0, "Kii": 50.0, "Te": 0.01, "xf": 0.15, "rf": 0.0}, _inner_pi_current_loop)
# <<< block inner/pi_current_loop

SHARED_PARAMS = {"Tf": 0.01}
NOMINAL_ANGULAR_FREQUENCY = "w0"            # filled in as 2*pi*60


class MenuError(Exception):
    pass


def allowed_options():
    """The blocks this harness offers, from tools/menu_options.json (every block if the file is missing)."""
    carried = {slot: list(choices) for slot, choices in BLOCKS.items()}
    if not os.path.exists(OPTIONS_FILE):
        return carried
    with open(OPTIONS_FILE) as file:
        listed = json.load(file)
    return {slot: [name for name in listed.get(slot, []) if name in carried[slot]] for slot in carried}


def check_choices(choices):
    """choices: {"pf":..., "qv":..., "voltage":..., "inner": ... (only with pi_voltage_loop)}."""
    allowed = allowed_options()
    for slot in ("pf", "qv", "voltage"):
        if choices.get(slot) not in allowed[slot]:
            raise MenuError(f"{slot} must be one of {allowed[slot]}, got {choices.get(slot)!r}")
    if choices["voltage"] == "pi_voltage_loop":
        if choices.get("inner") not in allowed["inner"]:
            raise MenuError(f"inner must be one of {allowed['inner']} with pi_voltage_loop, got {choices.get('inner')!r}")
    elif choices.get("inner") not in (None, "", "none"):
        raise MenuError("inner applies only to pi_voltage_loop; leave it out for voltage_behind_reactance")


def parameter_defaults(choices):
    """Every parameter the structure uses, with its default value, in a stable order."""
    check_choices(choices)
    params = dict(SHARED_PARAMS)
    for slot in ("pf", "qv", "voltage", "inner"):
        choice = choices.get(slot)
        if choice and slot in BLOCKS and choice in BLOCKS[slot]:
            params.update(BLOCKS[slot][choice]["params"])
    return params


def build_submission(choices, params=None):
    """The submission dict for these blocks; params overrides the defaults (unknown names are an error)."""
    defaults = parameter_defaults(choices)
    params = dict(params or {})
    unknown = set(params) - set(defaults)
    if unknown:
        raise MenuError(f"parameters {sorted(unknown)} are not used by this structure (it uses {list(defaults)})")
    values = {**defaults, **{name: float(value) for name, value in params.items()}}
    values["w0"] = 376.99111843077515                 # 2*pi*60 rad/s
    defs, states = {}, {}
    pf, qv, voltage, inner = choices["pf"], choices["qv"], choices["voltage"], choices.get("inner")
    delta_init = BLOCKS["voltage"][voltage]["prepare"](defs)       # the starting internal angle (and E0)
    # measurement filters (their rhs use Pe, Qe, defined last)
    states["Pf"] = {"rhs": "(Pe - Pf)/Tf", "init": "P0"}
    states["Qf"] = {"rhs": "(Qe - Qf)/Tf", "init": "Q0"}
    BLOCKS["pf"][pf]["build"](defs, states, delta_init)
    defs["vd"] = "V*cos(delta - theta)"
    defs["vq"] = "-V*sin(delta - theta)"
    BLOCKS["qv"][qv]["build"](defs, states)
    BLOCKS["voltage"][voltage]["build"](defs, states, inner)
    defs["Pe"] = "vd*Id + vq*Iq"
    defs["Qe"] = "-vd*Iq + vq*Id"
    return {"params": values, "defs": defs, "states": states, "outputs": {"P": "Pe", "Q": "Qe"},
            "notes": f"structure_menu blocks: {json.dumps({k: v for k, v in choices.items() if v})}"}


def choices_from(options):
    choices = {"pf": options.pf, "qv": options.qv, "voltage": options.voltage}
    if options.inner:
        choices["inner"] = options.inner
    return choices


def print_menu():
    allowed = allowed_options()
    print(f"shared parameters (every structure): {SHARED_PARAMS}   (w0 = 2*pi*60 rad/s is fixed)")
    for slot in ("pf", "qv", "voltage", "inner"):
        print(f"\n--{slot}" + ("   (only with --voltage pi_voltage_loop)" if slot == "inner" else ""))
        for name in allowed[slot]:
            block = BLOCKS[slot][name]
            print(f"  {name}: {block['about']}\n      parameters (defaults): {block['params'] or 'none'}")
    count = sum(len(allowed["inner"]) if voltage == "pi_voltage_loop" else 1 for voltage in allowed["voltage"])
    print(f"\n{len(allowed['pf']) * len(allowed['qv']) * count} structures in all.")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build a submission from a menu of control blocks.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    build = commands.add_parser("build")
    for slot in ("pf", "qv", "voltage"):
        build.add_argument(f"--{slot}", required=True)
    build.add_argument("--inner")
    build.add_argument("--params", help="JSON file of parameter values (a fit_structure.py result works too)")
    build.add_argument("--out", default="submission.json")
    options = parser.parse_args(argv)
    if options.command == "list":
        print_menu()
        return 0
    try:
        params = None
        if options.params:
            with open(options.params) as file:
                loaded = json.load(file)
            params = loaded.get("params", loaded)
        submission = build_submission(choices_from(options), params)
    except MenuError as error:
        print(f"ERROR: {error}")
        return 1
    with open(options.out, "w") as file:
        json.dump(submission, file, indent=1)
    print(f"wrote {options.out}: {len(submission['states'])} states, parameters {submission['params']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
