"""Small deterministic byte-unigram reference for byte_next_v1 tasks."""


class Model:
    def __init__(self, config, weights):
        if config.get("response_space_profile") != "byte_next_v1":
            raise ValueError("Wrong byte-sequence profile")
        probabilities = weights.get("byte_probabilities")
        if type(probabilities) is not list or len(probabilities) != 257:
            raise ValueError("Expected probabilities for 256 bytes plus EOS")
        self.probabilities = [float(p) for p in probabilities]

    def predict_next(self, prefix, response_prefix_bytes):
        # A deliberately simple training-only reference: no current target is
        # passed in, and no state is fitted during inference.
        if type(prefix) is not str or not prefix.endswith("<<") or type(response_prefix_bytes) is not bytes:
            raise ValueError("Invalid causal byte query")
        return self.probabilities
