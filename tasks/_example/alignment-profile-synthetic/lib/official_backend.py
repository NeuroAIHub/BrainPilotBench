"""Explicit extension point. Never substitute synthetic outputs for real evidence."""


def load_official_profile(*args, **kwargs):
    raise NotImplementedError('Real Brain-Score score/prediction packets are not integrated or accepted; no data is downloaded.')
