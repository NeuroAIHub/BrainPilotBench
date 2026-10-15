"""Fixed power-spectrum reference with a variable number of iEEG channels."""

import torch


class Model(torch.nn.Module):
    def __init__(self, config):
        super().__init__()
        self.linear = torch.nn.Linear(12, 1)
        self.mean = config["feature_mean"]
        self.scale = config["feature_scale"]

    def forward(self, window, subject_id):
        if window.ndim != 2 or window.shape[1] != 512 or not isinstance(subject_id, str):
            raise ValueError("Expected float32[C,512] and an opaque subject ID")
        spectrum = torch.fft.rfft(window, n=512, dim=-1)
        power = (spectrum.real.square() + spectrum.imag.square()) / 512
        frequencies = torch.fft.rfftfreq(512, d=1 / 256)
        values = []
        for lower, upper in ((1, 4), (4, 8), (8, 13), (13, 30), (30, 80), (80, 120)):
            band = torch.log10(power[:, (frequencies >= lower) & (frequencies < upper)].mean(-1) + 1e-20)
            values.extend((torch.quantile(band, 0.5), torch.quantile(band, 0.75)))
        features = torch.stack(values)
        mean = torch.tensor(self.mean, dtype=torch.float32)
        scale = torch.tensor(self.scale, dtype=torch.float32)
        return torch.sigmoid(self.linear((features - mean) / scale)).reshape(())
