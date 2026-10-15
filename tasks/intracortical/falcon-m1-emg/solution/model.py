"""Stateless M1 streaming Ridge reference architecture.

The trusted reference generator supplies weights. A submitted Agent may replace
this model, but must keep the Model/reset/forward interface and frozen output
shape. Inference runs in the separately pinned CPU Docker image.
"""

import torch


class Model(torch.nn.Module):
    def __init__(self, config=None):
        super().__init__()
        self.linear = torch.nn.Linear(64, 16)

    def reset(self):
        """Reset at each run/file boundary; this linear reference has no history."""
        return None

    def forward(self, x: torch.Tensor, trial_start: bool = False) -> torch.Tensor:
        if x.ndim != 1 or x.shape[0] != 64 or x.dtype != torch.float32:
            raise ValueError("M1 expects one float32[64] observation per 20 ms")
        return self.linear(x)
