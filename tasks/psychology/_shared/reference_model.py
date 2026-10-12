"""Public response-space contracts for categorical Psych-101 tasks.

Only the current causal prefix and a public task profile determine the legal
responses. Neither the observed answer nor future text is needed.
"""

import re


IOWA_PROFILE = "iowa_four_deck_v0"
CASINO_PROFILE = "casino_two_machine_v1"
GERSHMAN_PROFILE = "gershman_two_machine_v1"
HILBIG_PROFILE = "hilbig_two_product_v1"
WILSON_PROFILE = "wilson_two_machine_v1"
SPEEKENBRINK_PROFILE = "speekenbrink_weather_v1"
LUDWIG_PROFILE = "ludwig_left_right_v1"
SCHULZ_PROFILE = "schulz_eight_option_v1"

_IOWA = re.compile(
    r"\AYou see in front of you four decks of cards labeled "
    r"([A-Za-z]), ([A-Za-z]), ([A-Za-z]), and ([A-Za-z])\."
)
_CASINO_PENDING = re.compile(
    r"(?:\A|\n)You go to casino ([1-4])\. "
    r"You can choose between machines ([A-Z]) and ([A-Z])\. You press <<\Z"
)
_GERSHMAN_INTRO = re.compile(
    r"\AIn this task, you have to repeatedly choose between two slot machines "
    r"labeled ([A-Z]) and ([A-Z])\."
)
_HILBIG_INTRO = re.compile(
    r"\AYou are repeatedly presented with two options, labeled ([A-Z]) and ([A-Z])\."
)
_HILBIG_PENDING = re.compile(
    r"(?:\A|\n)Product ([A-Z]) ratings: \[[01](?: [01]){3}\]\. "
    r"Product ([A-Z]) ratings: \[[01](?: [01]){3}\]\. You press <<\Z"
)
_WILSON_INTRO = re.compile(
    r"\AYou are participating in multiple games involving two slot machines, "
    r"labeled ([A-Z]) and ([A-Z])\."
)
_SPEEKENBRINK_INTRO = re.compile(
    r"predicts rainy weather \(by pressing ([A-Z])\) or fine weather "
    r"\(by pressing ([A-Z])\)\."
)
_SPEEKENBRINK_PENDING = re.compile(
    r"(?:\A|\n)You are seeing the following: card [1-4]"
    r"(?:, card [1-4]){0,2}\. You press <<\Z"
)
_LUDWIG_INTRO = re.compile(
    r"You can press ([A-Z]) to go left, and ([A-Z]) to go right\."
)
_SCHULZ_INTRO = re.compile(
    r"You can choose between options (1), (2), (3), (4), (5), (6), (7) and (8) "
    r"by pressing the corresponding key\."
)


def displayed_options(prefix: str, spec: dict | None = None) -> tuple[str, ...]:
    """Return the exact legal response keys for one pending decision.

    Legacy Iowa specs have no profile; this remains their four-deck contract.
    The casino contract derives both options from the *current* prompt because
    labels can differ across casinos, participants, and trials. Gershman's
    machine keys come from the participant's visible instructions; Hilbig's
    product keys must also match the current ratings line.
    """

    if type(prefix) is not str or not prefix.endswith("<<"):
        raise ValueError("Expected a causal prefix ending at the open response marker")
    if spec is not None and type(spec) is not dict:
        raise TypeError("Task spec must be a dictionary")
    profile = (spec or {}).get("response_space_profile", IOWA_PROFILE)
    if profile == IOWA_PROFILE:
        match = _IOWA.match(prefix)
        if match is None or not prefix.endswith("You press <<"):
            raise ValueError("Unsupported or ambiguous Iowa response space")
        options = match.groups()
    elif profile == CASINO_PROFILE:
        match = _CASINO_PENDING.search(prefix)
        if match is None:
            raise ValueError("Unsupported or ambiguous casino response space")
        options = match.groups()[1:]
    elif profile == GERSHMAN_PROFILE:
        intro = _GERSHMAN_INTRO.match(prefix)
        if intro is None or not prefix.endswith("\nYou press <<"):
            raise ValueError("Unsupported or ambiguous Gershman response space")
        options = intro.groups()
    elif profile == HILBIG_PROFILE:
        intro = _HILBIG_INTRO.match(prefix)
        current = _HILBIG_PENDING.search(prefix)
        if intro is None or current is None or intro.groups() != current.groups():
            raise ValueError("Unsupported or ambiguous Hilbig response space")
        options = current.groups()
    elif profile == WILSON_PROFILE:
        intro = _WILSON_INTRO.match(prefix)
        if intro is None or not prefix.endswith("\nYou press <<"):
            raise ValueError("Unsupported or ambiguous Wilson response space")
        options = intro.groups()
    elif profile == SPEEKENBRINK_PROFILE:
        intro = _SPEEKENBRINK_INTRO.search(prefix)
        if intro is None or _SPEEKENBRINK_PENDING.search(prefix) is None:
            raise ValueError("Unsupported or ambiguous Speekenbrink response space")
        options = intro.groups()
    elif profile == LUDWIG_PROFILE:
        intro = _LUDWIG_INTRO.search(prefix)
        if intro is None or not prefix.endswith("\nYou press <<"):
            raise ValueError("Unsupported or ambiguous Ludwig response space")
        options = intro.groups()
    elif profile == SCHULZ_PROFILE:
        intro = _SCHULZ_INTRO.search(prefix)
        if intro is None or not prefix.endswith("\nYou press <<"):
            raise ValueError("Unsupported or ambiguous Schulz response space")
        options = intro.groups()
    else:
        raise ValueError(f"Unknown response-space profile: {profile!r}")
    if len(set(options)) != len(options):
        raise ValueError("Duplicate displayed response keys")
    return options


def checked_probabilities(values: dict, options: tuple[str, ...]) -> dict[str, float]:
    """Validate an exact normalized distribution over the displayed options."""

    import math

    if type(values) is not dict or set(values) != set(options):
        raise ValueError("Predicted response keys differ from displayed options")
    if any(type(value) not in (int, float) or not math.isfinite(value)
           or not 0 <= value <= 1 for value in values.values()):
        raise ValueError("Invalid response probability")
    if not math.isclose(sum(values.values()), 1, rel_tol=0, abs_tol=1e-8):
        raise ValueError("Response probabilities are not normalized")
    return values

_CASINO_CURRENT = re.compile(
    r"You go to casino ([1-4])\. You can choose between machines ([A-Z]) and ([A-Z])\. You press <<\Z"
)
_CASINO_PAST = re.compile(
    r"You go to casino ([1-4])\. You can choose between machines ([A-Z]) and ([A-Z])\. You press <<([A-Z])>>"
)


def last_casino_choice(prefix):
    """Return the latest completed choice in the current casino, if one exists."""
    current = _CASINO_CURRENT.search(prefix)
    if current is None:
        raise ValueError("Unsupported casino prefix")
    previous = [match.group(4) for match in _CASINO_PAST.finditer(prefix)
                if match.group(1) == current.group(1)]
    return previous[-1] if previous else None


class Model:
    """Small deterministic public-data reference with causal casino history."""

    def __init__(self, config, weights):
        self.profile = config["response_space_profile"]
        self.method = config["reference_method"]
        self.probabilities = weights["option_probabilities"]
        if type(self.probabilities) is not list or len(self.probabilities) < 2:
            raise ValueError("Missing reference probabilities")

    def predict(self, prefix):
        options = displayed_options(prefix, {"response_space_profile": self.profile})
        if len(options) != len(self.probabilities):
            raise ValueError("Reference response-space size changed")
        if self.method == "casino_stay_prior":
            previous = last_casino_choice(prefix)
            if previous in options:
                p = float(self.probabilities[0])
                return {key: p if key == previous else 1.0 - p for key in options}
            return {key: 1.0 / len(options) for key in options}
        return {key: float(self.probabilities[i]) for i, key in enumerate(options)}
