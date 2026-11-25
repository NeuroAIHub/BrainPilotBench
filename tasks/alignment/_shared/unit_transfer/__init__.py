"""L2 unit discovery on Tuckute, with fixed-unit transfer to Pereira384."""

from multiscale import ALPHA, INSPECTIONS, K, POSITIONS

PROTOCOL = 'alignment-l2-unit-transfer-v1'
MODELS = ('distilgpt2', 'gpt2-small', 'llama-3.2-1b')
CONTROLS = ('token_count', 'mean_next_token_surprisal_nats')
