"""Fixed Train-text streaming interface reference, not a trained decoder."""

import torch


class Model(torch.nn.Module):
    def __init__(self, config):
        super().__init__()
        self.anchor = torch.nn.Parameter(torch.zeros(1))
        self.text = config["train_sentence"]
        self.observed = 0

    def reset(self):
        self.observed = 0
        return None

    def observe(self, x: torch.Tensor, trial_start: bool = False):
        if x.shape != (192,) or x.dtype != torch.float32:
            raise ValueError("H2 requires the current float32[192] bin")
        if trial_start:
            self.observed = 0
        self.observed += 1
        return None

    def finish_trial(self):
        if self.observed < 1:
            raise ValueError("A complete trial needs at least one neural bin")
        self.observed = 0
        return self.text
