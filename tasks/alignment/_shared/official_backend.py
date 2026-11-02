"""Explicit real server backend; never substitute synthetic calculations."""
from real_brainscore import COMMIT, BENCHMARK


def run_official(inputs, output, layer=None, device='cpu'):
    from real_brainscore.pipeline import score_fixed
    return score_fixed(inputs, output, layer=layer, device=device)
