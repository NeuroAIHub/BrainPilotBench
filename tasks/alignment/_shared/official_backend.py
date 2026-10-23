"""Explicit future seam. Never substitutes a NumPy/scikit-learn ridge implementation."""
COMMIT = '3b4fde5d6f53a69c652c7a1128397549995547b0'
BENCHMARK = 'Pereira2018.384sentences-ridge'


def run_official(inputs, output):
    raise NotImplementedError(
        'Official Brain-Score backend is not accepted. Requires pinned transitive dependencies, '
        'model/tokenizer revisions, original assembly coordinates and ceiling, traced fold predictions, '
        'and official-entry/traced-entry plus live/cache equivalence evidence. No fallback is available.')
