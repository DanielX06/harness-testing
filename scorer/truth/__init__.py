"""True device models written as submissions, one module per device model.

The scorer picks the builder by the "device" field of a grid's answer key, so adding a device (REGF2,
REGF3) means adding a module here and one line to TRUTH_SPEC_BUILDERS.
"""
from scorer.truth.regf1_as_submission import regf1_truth_spec
from scorer.truth.regf2_as_submission import regf2_truth_spec
from scorer.truth.regf3_as_submission import regf3_truth_spec

TRUTH_SPEC_BUILDERS = {"REGF1": regf1_truth_spec, "REGF2": regf2_truth_spec, "REGF3": regf3_truth_spec}
# droops a device does not have, so the droop component (PAR) leaves them out on its grids: REGF3 returns Q to
# Q0 in steady state (scorer/truth/regf3_as_submission.py), so it has no Q-V droop. The frequency-response Q/V
# entry still scores the Q-V behaviour from 0.1 Hz up. Any other truth gain that does not converge is an error.
DROOPS_ABSENT = {"REGF3": ("volt",)}


def truth_spec_for(device_model, params_used, rating_mva):
    """The true device as a submission dict, built from an answer key's device name and parameters."""
    if device_model not in TRUTH_SPEC_BUILDERS:
        raise ValueError(f"no truth model for device {device_model!r}; add one to scorer/truth/ "
                         f"(have {sorted(TRUTH_SPEC_BUILDERS)})")
    return TRUTH_SPEC_BUILDERS[device_model](params_used, inner_loop="full", rating_mva=float(rating_mva))
