"""REGF2 (ANDES 2.0.0, regf2.py, with the PLL2 that ANDES adds to its bus) written as a submission. Trusted
truth model.

REGF2 is REGF1 with the droop law replaced by a virtual synchronous machine: the frequency command passes through
a first-order lag with time constant Tint = mf*wdrp (the VSM inertia), and a PLL's measured frequency deviation,
times dd*wdrp, adds damping. Everything else (filters, power and reactive limiter PIs, Q-V droop, voltage and
current loops, output lag) is REGF1's, so this builds on regf1_truth_spec. ANDES's REGF2 equations:

    Tint*d(INTw)/dt = dd*wdrp*plldw + wref + wdrp*(PIplim - Psen) - INTw,   INTw(0) = wref = 1
    dw = w0*(INTw - wref)                                                    (REGF1: dw = w0*wdrp*(PIplim - Psen))
    PLL2: vq_pll = V*sin(theta - am),  plldw = Kp*vq_pll + xpll,  d(xpll)/dt = Ki*vq_pll,  d(am)/dt = w0*plldw

The builder adds REGF2 without a PLL, so ANDES adds a PLL2 with its defaults (Kp = Ki = 0.1); PLL_DEFAULTS
below must match that. As with REGF1, wdrp and Qdrp are the ANDES inputs (converter-base droop x Sb/Sn), and the
limiters are left out because none binds in any recording (build_test_grids.py checks Psig, Qsig and dw).
Written out, a spec carries the true parameters: keep it away from the agent and the updater.
"""
import json

from scorer.truth.regf1_as_submission import regf1_truth_spec

# REGF2's own ANDES defaults, and the PLL2 that ANDES adds to the device's bus
REGF2_DEFAULTS = {"mf": 0.15, "dd": 0.11}
PLL_DEFAULTS = {"Kpll": 0.1, "Kipll": 0.1}


def regf2_truth_spec(params_used, inner_loop="full", rating_mva=900.0, system_base_mva=100.0,
                     filter_reactance=0.2, filter_resistance=0.0, nominal_frequency_hz=60.0, parameter_scale=None):
    """REGF2 as a submission dict. params_used: the ANDES inputs from an answer key (missing ones take ANDES's
    defaults; Kpll and Kipll, if given, are the PLL's gains). parameter_scale: {name: factor}, to build a
    deliberately wrong version (REGF1's parameters, mf, dd, Kpll or Kipll)."""
    regf1_scale = {name: factor for name, factor in (parameter_scale or {}).items()
                   if name not in REGF2_DEFAULTS and name not in PLL_DEFAULTS}
    spec = regf1_truth_spec(params_used, inner_loop=inner_loop, rating_mva=rating_mva, system_base_mva=system_base_mva,
                            filter_reactance=filter_reactance, filter_resistance=filter_resistance,
                            nominal_frequency_hz=nominal_frequency_hz, parameter_scale=regf1_scale)
    own = dict(REGF2_DEFAULTS, **PLL_DEFAULTS)
    own.update({name: float(value) for name, value in params_used.items() if name in own})
    for name, factor in (parameter_scale or {}).items():
        if name in own:
            own[name] *= factor
    spec["params"].update(own)
    # the VSM lag replaces REGF1's droop law; dict order is kept, so dw stays where REGF1's defs put it
    spec["defs"]["dw"] = "w0*(INTw - 1)"
    spec["defs"].update({"Tint": "mf*wdrp", "vq_pll": "V*sin(theta - am)", "plldw": "Kpll*vq_pll + xpll"})
    spec["states"].update({
        "INTw": {"rhs": "(dd*wdrp*plldw + 1 + wdrp*(PIplim - Psen) - INTw)/Tint", "init": "1"},
        "xpll": {"rhs": "Kipll*vq_pll", "init": "0"},
        "am": {"rhs": "w0*plldw", "init": "theta0"},
    })
    return spec


def write_truth_spec(path, answer_key_path, inner_loop="full", parameter_scale=None):
    """Write the truth spec for the device in an answer key to path (JSON). Returns path."""
    with open(answer_key_path) as file:
        key = json.load(file)
    with open(path, "w") as file:
        json.dump(regf2_truth_spec(key["params_used"], inner_loop=inner_loop, parameter_scale=parameter_scale),
                  file, indent=1)
    return path
