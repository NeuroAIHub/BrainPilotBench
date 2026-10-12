import torch


class Model(torch.nn.Module):
    def __init__(self, config):
        super().__init__()
        self.register_buffer('mean', torch.zeros(253))
        self.register_buffer('scale', torch.ones(253))
        self.register_buffer('coef', torch.zeros(254, 4))

    def features(self, x):
        x = x - x.mean(-1, keepdim=True)
        covariance = x @ x.transpose(1, 2) / x.shape[-1]
        variance = covariance.diagonal(dim1=1, dim2=2).clamp_min(1e-12)
        correlation = covariance / torch.sqrt(variance[:, :, None] * variance[:, None, :])
        pairs = torch.triu_indices(22, 22, 1, device=x.device)
        return torch.cat([variance.log(), correlation[:, pairs[0], pairs[1]]], dim=1)

    def forward(self, x):
        z = (self.features(x) - self.mean) / self.scale
        z = torch.cat([z, torch.ones((len(z), 1), device=x.device)], dim=1)
        return torch.softmax(z @ self.coef, dim=1)
