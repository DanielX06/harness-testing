"""True device models written as submissions, one module per device model.

The scorer picks the builder by the "device" field of a grid's answer key, so adding a device (REGF2,
REGF3) means adding a module here and one line to TRUTH_SPEC_BUILDERS.
"""
from scorer.truth.regf1_as_submission import regf1_truth_spec

TRUTH_SPEC_BUILDERS = {"REGF1": regf1_truth_spec}


def truth_spec_for(device_model, params_used, rating_mva):
    """The true device as a submission dict, built from an answer key's device name and parameters."""
    if device_model not in TRUTH_SPEC_BUILDERS:
        raise ValueError(f"no truth model for device {device_model!r}; add one to scorer/truth/ "
                         f"(have {sorted(TRUTH_SPEC_BUILDERS)})")
    return TRUTH_SPEC_BUILDERS[device_model](params_used, inner_loop="full", rating_mva=float(rating_mva))
