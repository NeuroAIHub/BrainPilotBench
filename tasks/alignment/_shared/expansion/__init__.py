"""Experimental alignment tasks B–F. No automatic downloads or registration."""

TASKS = {
    'B': ('alignment-context-dependence', 'pereira384-context-v2'),
    'C': ('alignment-brain-behavior', 'things-brain-behavior-v1'),
    'D': ('alignment-temporal-correspondence', 'things-eeg2-temporal-v1'),
    'E': ('alignment-learning-transfer', 'human-ann-transfer-v1'),
    'F': ('alignment-stimulus-selection', 'language-stimulus-selection-v1'),
}


class ExpansionError(ValueError):
    pass
