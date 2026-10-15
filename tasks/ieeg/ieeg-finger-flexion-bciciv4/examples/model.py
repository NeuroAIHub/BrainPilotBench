"""Fixed 100-ms log-power ridge reference; train all three heads on Train only."""
import torch


class Head(torch.nn.Module):
    def __init__(self, channels):
        super().__init__()
        self.register_buffer("mean", torch.zeros(channels, dtype=torch.float64))
        self.register_buffer("std", torch.ones(channels, dtype=torch.float64))
        self.register_buffer("weights", torch.zeros((channels, 5), dtype=torch.float64))
        self.register_buffer("target_mean", torch.zeros(5, dtype=torch.float64))


class Model(torch.nn.Module):
    def __init__(self, config):
        super().__init__()
        if config != {"reference": "fixed-100ms-ridge-v1", "ridge_alpha": 1.0}:
            raise ValueError("unsupported reference configuration")
        self.heads = torch.nn.ModuleDict({s: Head(c) for s, c in (("sub1", 62), ("sub2", 48), ("sub3", 64))})

    def forward(self, x, subject_id):
        head = self.heads[subject_id]
        if x.shape[0] % 100:
            raise ValueError("reference requires complete 100-ms windows")
        windows = x.double().reshape(-1, 100, x.shape[1])
        centered = windows - windows.mean(dim=1, keepdim=True)
        features = torch.log1p(centered.square().mean(dim=1))
        prediction = ((features - head.mean) / head.std) @ head.weights + head.target_mean
        return prediction.repeat_interleave(100, dim=0).float()
