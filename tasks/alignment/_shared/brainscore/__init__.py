"""Offline scale-up contracts. Importing this package never loads upstream data."""


class ScaleUpError(ValueError):
    """Invalid registry, packet or unresolved preparation requirement."""
