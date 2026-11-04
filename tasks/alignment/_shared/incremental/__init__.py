"""Derived incremental-prediction task. Imports do not load models or data."""

PROTOCOL = 'pereira384-incremental-ridge-v2'
TASK_ID = 'alignment-incremental-explanation'
VERSION = '0.2-server-draft'


class IncrementalError(ValueError):
    pass
