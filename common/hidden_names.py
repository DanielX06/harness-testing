"""Names the agents must never see: the simulator, the test case and the device model.

The solver's data, the harness files and anything shown to the updater are checked against this pattern.
Text an agent wrote itself has matches replaced instead (see remove_hidden_device_names).
"""
import re

SIMULATOR_AND_DEVICE_NAMES = re.compile(r"andes|regf|kundur|epri|grid.?forming|gfm|genrou|vsm|tgov|exdc", re.I)
NAME_REMOVED = "[name removed]"


def remove_hidden_device_names(text):
    """(text with every match replaced by [name removed], number of replacements)"""
    return SIMULATOR_AND_DEVICE_NAMES.subn(NAME_REMOVED, text)
