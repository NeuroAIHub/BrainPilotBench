"""Scalar normalization checks only; upstream fitting/aggregation remains upstream."""
import math

from .registry import require


def normalize(raw, ceiling, method):
    require(type(raw) in (int, float) and type(ceiling) in (int, float)
            and math.isfinite(raw) and math.isfinite(ceiling) and ceiling > 0, 'finite raw score and positive ceiling required')
    require(method in ('vision-explained-variance', 'language-ceiling'), 'unsupported normalization')
    value = raw * raw / ceiling if method == 'vision-explained-variance' else raw / ceiling
    require(math.isfinite(value), 'normalization overflow')
    normalized = value if method == 'vision-explained-variance' else min(1., max(0., value))
    return {'raw': raw, 'ceiling': ceiling, 'normalized': normalized, 'unclipped': value, 'normalization': method}
