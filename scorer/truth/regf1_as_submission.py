"""REGF1 (ANDES 2.0.0, regf1.py) written as a submission. Trusted truth model.

Used as the reference for the frequency-response and droop components, and by the tests (the ceiling, and
deliberately wrong versions). The voltage reference is the live setpoint Vset (in ANDES the vref service,
which the staged voltage-reference steps alter), so this spec follows those steps exactly as REGF1 does.
Written out, a spec carries the true parameters: keep it away from the agent and the updater.
Closed loop in ANDES, the "full" spec reproduces the case CSVs to within about 6e-6 pu.

inner_loop="full"  : all 13 ANDES states (current loop and output lag included); exactly the model that
                     produced the case data, so closed loop it must reproduce the CSVs.
inner_loop="ideal" : current loop algebraic (Id = Idref, Iq = Iqref), 9 states.
"""
import json
import math

DEFAULT_PARAMS = {"Tr": 0.005, "Te": 0.005, "Tpm": 0.025, "KPplim": 5.0, "KIplim": 30.0, "KPqlim": 0.1,
                  "KIqlim": 1.5, "KPv": 3.0, "KIv": 10.0, "KPi": 0.5, "KIi": 20.0, "wdrp": 0.033,
                  "Qdrp": 0.045}


def regf1_truth_spec(params_used, inner_loop="full", rating_mva=900.0, system_base_mva=100.0,
                     filter_reactance=0.2, filter_resistance=0.0, nominal_frequency_hz=60.0, parameter_scale=None):
    """REGF1 as a submission dict. params_used: the ANDES inputs from an answer key (missing ones take ANDES's
    defaults). filter_reactance and filter_resistance are on the device base. parameter_scale: {name: factor},
    to build a deliberately wrong version."""
    p = dict(DEFAULT_PARAMS)
    p.update({name: float(value) for name, value in params_used.items() if name in DEFAULT_PARAMS})
    for name, factor in (parameter_scale or {}).items():
        p[name] *= factor
    p.update(k=rating_mva / system_base_mva, w0=2 * math.pi * nominal_frequency_hz,
             xf=filter_reactance * system_base_mva / rating_mva, rf=filter_resistance * system_base_mva / rating_mva)
    defs = {
        "vd": "V*cos(delta - theta)",
        "vq": "-V*sin(delta - theta)",
        "PIplim": "KPplim*(Psig - Psen) + xp",
        "PIqlim": "KPqlim*(Qsig - Qsen) + xq",
        "dw": "w0*wdrp*(PIplim - Psen)",
        "vref2": "(PIqlim - Qsen)*Qdrp + Vset",
        "Idref": "KPv*(vref2 - vd) + xvd",
        "Iqref": "KPv*(-vq) + xvq",
    }
    if inner_loop == "full":
        defs.update({
            "det": "rf**2 + xf**2",
            "Id": "(rf*(ud - vd) + xf*(uq - vq))/det",
            "Iq": "(-xf*(ud - vd) + rf*(uq - vq))/det",
            "PIId": "KPi*(Idref - Id) + xid",
            "PIIq": "KPi*(Iqref - Iq) + xiq",
            "udref": "PIId + vd + rf*Id - xf*Iq",
            "uqref": "PIIq + vq + rf*Iq + xf*Id",
        })
    else:
        defs.update({"Id": "Idref", "Iq": "Iqref"})
    defs.update({"Pe": "vd*Id + vq*Iq", "Qe": "-vd*Iq + vq*Id"})
    states = {
        "Psen": {"rhs": "(Pe - Psen)/Tr", "init": "P0*k"},
        "Qsen": {"rhs": "(Qe - Qsen)/Tr", "init": "Q0*k"},
        "Psig": {"rhs": "(Psen - Psig)/Tpm", "init": "P0*k"},
        "Qsig": {"rhs": "(Qsen - Qsig)/Tpm", "init": "Q0*k"},
        "xp": {"rhs": "KIplim*(Psig - Psen)", "init": "P0*k"},
        "xq": {"rhs": "KIqlim*(Qsig - Qsen)", "init": "Q0*k"},
        "delta": {"rhs": "dw", "init": "theta0"},
        "xvd": {"rhs": "KIv*(vref2 - vd)", "init": "P0*k/V0"},
        "xvq": {"rhs": "KIv*(-vq)", "init": "-Q0*k/V0"},
    }
    if inner_loop == "full":
        states.update({
            "xid": {"rhs": "KIi*(Idref - Id)", "init": "0"},
            "xiq": {"rhs": "KIi*(Iqref - Iq)", "init": "0"},
            "ud": {"rhs": "(udref - ud)/Te", "init": "V0 + rf*P0*k/V0 + xf*Q0*k/V0"},
            "uq": {"rhs": "(uqref - uq)/Te", "init": "-rf*Q0*k/V0 + xf*P0*k/V0"},
        })
    else:
        for name in ("KPi", "KIi", "Te", "rf", "xf"):
            p.pop(name)
    return {"params": p, "defs": defs, "states": states, "outputs": {"P": "Pe/k", "Q": "Qe/k"}}


def write_truth_spec(path, answer_key_path, inner_loop="full", parameter_scale=None):
    """Write the truth spec for the device in an answer key to path (JSON). Returns path."""
    with open(answer_key_path) as file:
        key = json.load(file)
    with open(path, "w") as file:
        json.dump(regf1_truth_spec(key["params_used"], inner_loop=inner_loop, parameter_scale=parameter_scale),
                  file, indent=1)
    return path
