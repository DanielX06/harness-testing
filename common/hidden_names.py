"""Names the agents must never see: the simulator, the test case and the device model.

Since Nov 10 the device class is not hidden: grid-forming, GFM and VSM are allowed, because the base harness
gives the solver the WECC generic grid-forming models. What stays hidden is what would point to the simulator's
own device models and test case: ANDES, its REGF1/REGF2/REGF3 (the pattern also catches the WECC names REGFM_A1
and REGFM_B1, so harness text describes those models without their names), Kundur, EPRI (whose memo the
simulator's models follow) and the simulator's generator, governor and exciter names.

The solver's data, the harness files and anything shown to the updater are checked against this pattern.
Text an agent wrote itself has matches replaced instead (see remove_hidden_device_names).
"""
import re

SIMULATOR_AND_DEVICE_NAMES = re.compile(r"andes|regf\w*|kundur|epri|genrou|tgov|exdc", re.I)
NAME_REMOVED = "[name removed]"


def remove_hidden_device_names(text):
    """(text with every match replaced by [name removed], number of replacements)"""
    return SIMULATOR_AND_DEVICE_NAMES.subn(NAME_REMOVED, text)
