"""REGF3 (ANDES 2.0.0, regf3.py) written as a submission. Trusted truth model.

REGF3 is REGF1 with the primary controls replaced by dispatchable virtual oscillator control (dVOC).
Everything else (filters, power and reactive limiter PIs, voltage and current loops, output lag) is REGF1's,
so this builds on regf1_truth_spec. ANDES's REGF3 equations:

    Kdvoc = wdrp*4e8 / (1e8 - 2*(100 - 100*Qdrp)**2 - 1e4)**2          (a constant service)
    dw    = w0*wdrp*(PIplim - Psen)/vref2**2                            (REGF1: w0*wdrp*(PIplim - Psen))
    derv  = wdrp/vref2*(PIqlim - Qsen) + vref2*Kdvoc*(Vref + vref2)*(Vref - vref2)
    d(vref2)/dt = w0*derv,  vref2(0) = vd0 = V0                         (REGF1: vref2 algebraic, Q-V droop)
    Vref  = vref, the setpoint service the staged voltage-reference steps alter (Vset here)

Two consequences of ANDES's numbers, both kept because this spec has to be the device ANDES simulates:
  * With any realistic wdrp and Qdrp, Kdvoc is about 1e-9 (1.3e-9 at ANDES's defaults), so the Vref term is
    negligible and a voltage-setpoint step barely moves the device.
  * vref2 integrates PIqlim - Qsen, which (with Qsig a lag of Qsen and no limit binding) returns Q to its
    t = 0 value: in steady state the unit holds Q, with no Q-V droop.
Qdrp enters only through Kdvoc. The limiters are left out, as for REGF1 (build_test_grids.py checks that
none binds). Written out, a spec carries the true parameters: keep it away from the agent and the updater.
"""
import json

from scorer.truth.regf1_as_submission import regf1_truth_spec


def dvoc_gain(wdrp, Qdrp):
    """ANDES's Kdvoc constant service, as regf3.py writes it."""
    return wdrp * 4e8 / (1e8 - 2 * (100 - 100 * Qdrp) ** 2 - 1e4) ** 2


def regf3_truth_spec(params_used, inner_loop="full", rating_mva=900.0, system_base_mva=100.0,
                     filter_reactance=0.2, filter_resistance=0.0, nominal_frequency_hz=60.0, parameter_scale=None):
    """REGF3 as a submission dict. params_used: the ANDES inputs from an answer key (missing ones take ANDES's
    defaults, which are REGF1's). parameter_scale: {name: factor}, to build a deliberately wrong version; a
    "Kdvoc" factor scales the dVOC gain after it is computed from wdrp and Qdrp."""
    scale = dict(parameter_scale or {})
    kdvoc_factor = scale.pop("Kdvoc", 1.0)
    spec = regf1_truth_spec(params_used, inner_loop=inner_loop, rating_mva=rating_mva, system_base_mva=system_base_mva,
                            filter_reactance=filter_reactance, filter_resistance=filter_resistance,
                            nominal_frequency_hz=nominal_frequency_hz, parameter_scale=scale)
    params = spec["params"]
    params["Kdvoc"] = dvoc_gain(params["wdrp"], params["Qdrp"]) * kdvoc_factor
    # vref2 becomes a state; dict order is kept so every def still follows what it uses
    defs = {}
    for name, expression in spec["defs"].items():
        if name == "vref2":
            continue
        defs[name] = expression
        if name == "dw":
            defs["dw"] = "w0*wdrp*(PIplim - Psen)/vref2**2"
            defs["derv"] = "wdrp/vref2*(PIqlim - Qsen) + vref2*Kdvoc*(Vset + vref2)*(Vset - vref2)"
    spec["defs"] = defs
    spec["states"]["vref2"] = {"rhs": "w0*derv", "init": "V0"}
    return spec


def write_truth_spec(path, answer_key_path, inner_loop="full", parameter_scale=None):
    """Write the truth spec for the device in an answer key to path (JSON). Returns path."""
    with open(answer_key_path) as file:
        key = json.load(file)
    with open(path, "w") as file:
        json.dump(regf3_truth_spec(key["params_used"], inner_loop=inner_loop, parameter_scale=parameter_scale),
                  file, indent=1)
    return path
