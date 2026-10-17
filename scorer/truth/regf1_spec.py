"""REGF1 (ANDES 2.0.0, regf1.py) written as a symbolic submission. Trusted truth model.

Used for the frequency-response and droop references, and by the tests (ceiling, sensitivity).
The voltage reference is the live setpoint Vset (ANDES: the vref service, which the staged
voltage-reference steps alter), so this spec follows those steps exactly as REGF1 does.
Written out, a spec carries the true parameters: keep it away from the agent and the updater.
Closed loop in ANDES, the "full" spec reproduces the case CSVs to within ~6e-6 pu.

inner="full"  : all 13 ANDES states (current loop and output lag included); this is exactly the
                model that produced the case data, so closed loop it must reproduce the CSVs.
inner="ideal" : current loop algebraic (Id = Idref, Iq = Iqref), 9 states.
"""
import json
import math

DEFAULTS = {"Tr": 0.005, "Te": 0.005, "Tpm": 0.025, "KPplim": 5.0, "KIplim": 30.0, "KPqlim": 0.1,
            "KIqlim": 1.5, "KPv": 3.0, "KIv": 10.0, "KPi": 0.5, "KIi": 20.0, "wdrp": 0.033,
            "Qdrp": 0.045}


def spec(params_used, inner="full", Sn=900.0, Sb=100.0, xf_dev=0.2, rf_dev=0.0, fn=60.0, scale=None):
    p = dict(DEFAULTS)
    p.update({k: float(v) for k, v in params_used.items() if k in DEFAULTS})
    for k, f in (scale or {}).items():
        p[k] *= f
    p.update(k=Sn / Sb, w0=2 * math.pi * fn, xf=xf_dev * Sb / Sn, rf=rf_dev * Sb / Sn)
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
    if inner == "full":
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
    if inner == "full":
        states.update({
            "xid": {"rhs": "KIi*(Idref - Id)", "init": "0"},
            "xiq": {"rhs": "KIi*(Iqref - Iq)", "init": "0"},
            "ud": {"rhs": "(udref - ud)/Te", "init": "V0 + rf*P0*k/V0 + xf*Q0*k/V0"},
            "uq": {"rhs": "(uqref - uq)/Te", "init": "-rf*Q0*k/V0 + xf*P0*k/V0"},
        })
    if inner != "full":
        for n in ("KPi", "KIi", "Te", "rf", "xf"):
            p.pop(n)
    return {"params": p, "defs": defs, "states": states, "outputs": {"P": "Pe/k", "Q": "Qe/k"}}


def write(path, answer_key_path, inner="full", scale=None):
    key = json.load(open(answer_key_path))
    with open(path, "w") as fh:
        json.dump(spec(key["params_used"], inner=inner, scale=scale), fh, indent=1)
    return path
