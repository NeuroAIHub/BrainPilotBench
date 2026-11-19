"""DistilGPT2 word-order experiment on the Task F population."""
import hashlib
import json

PROTOCOL = 'tuckute-mlp-word-order-v1'
POSITIONS = ('pre1', 'pre2')
K = 8
INSPECTIONS = 2
RANDOM_GROUPS = 8
ALPHA = 100.
ACT_THRESHOLD = .05  # training SD per unit
LOSS_THRESHOLD = .01  # natural log probability
CSV_SHA256 = 'a990474e5ecd9bdbbf07c0df81be6f724fc377fe888d07432097a7f7b115cee4'


def fingerprint(value):
    data = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    return hashlib.sha256(data).hexdigest()


def direction(value, threshold):
    return 'up' if value > threshold else 'down' if value < -threshold else 'flat'
