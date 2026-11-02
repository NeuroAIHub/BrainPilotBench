"""Server-side Brain-Score integration. Importing this package never loads data."""

COMMIT = '3b4fde5d6f53a69c652c7a1128397549995547b0'
BENCHMARK = 'Pereira2018.384sentences-ridge'
CACHE_SCHEMA = 'bpb-brainscore-cache/1'
REAL_PROFILE = 'pereira-subject-material-descriptive-v1'
REAL_TASK_ID = 'alignment-pereira2018-profile'
REAL_VERSION = '0.1-server-draft'


class BackendError(ValueError):
    """Invalid real inputs or unavailable runtime; never a synthetic fallback."""
