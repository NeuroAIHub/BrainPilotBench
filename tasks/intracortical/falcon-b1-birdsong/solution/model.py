"""Fixed Train-mean motif reference, not a trained neural decoder."""

import torch


class Model(torch.nn.Module):
    def __init__(self, config):
        super().__init__()
        self.register_buffer("template", torch.zeros(880, 158, dtype=torch.float32))

    def forward(self, neural: torch.Tensor) -> torch.Tensor:
        if neural.shape != (27000, 85) or neural.dtype != torch.float32:
            raise ValueError("B1 requires one complete float32[27000,85] motif")
        return self.template
