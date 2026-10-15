"""Normal invalid-submission cases for the isolated worker's contract tests."""
import torch


class Model(torch.nn.Module):
    def __init__(self, config):
        super().__init__()
        self.kind = config["kind"]
        self.register_buffer("counter", torch.zeros(1))

    def forward(self, x, subject_id):
        if self.kind == "mutation":
            self.counter.add_(1)
            return x[:, :5].clone()
        if self.kind == "shape":
            return x[:, :4].clone()
        raise ValueError("unknown fixture")
