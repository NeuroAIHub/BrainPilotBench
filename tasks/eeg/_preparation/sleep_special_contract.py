"""Exact scientific rules and the raw-array export contract for the sleep-onset /
sleep-arousal native cases.

This module is pure standard library on purpose: every rule below is a restatement
of a *pinned native* definition, so it can be unit-tested without torch, numpy or
any native package, and then cross-checked against the real native objects at
runtime (see ``sleep_special_expansion``). Nothing here replaces a native
computation in the reference run -- the native sampler, loss and metrics always
run as published; these functions exist to *independently* verify them and to
describe the arrays the Agent-side (frozen-array) backend will later need.

Pinned definitions this module mirrors (SHA a8092dc10956038e445ff0e07f9c0c7e03a10d36):

``neuralbench/metrics.py`` ``_assign_bins`` / ``BinnedMAE``
    ``bin = torch.bucketize(t, bin_boundaries[1:-1], right=True)``, i.e. the number
    of *inner* edges ``<= t`` -- a ``[lo, hi)`` convention -- while
    ``in_range = (t >= boundaries[0]) & (t <= boundaries[-1])`` additionally keeps a
    target sitting exactly on the *last* edge (the ``cap_s`` value) inside the last
    bin. ``compute`` returns the unweighted mean of the per-bin MAEs over
    **non-empty** bins, and NaN when every bin is empty.

``neuralbench/data.py`` ``RegressionBinSampler``
    "Targets are bucketised by ``bin_edges`` and assigned inverse-frequency sampling
    weights so that, in expectation, every populated bin contributes the same total
    mass"; "Targets outside ``[bin_edges[0], bin_edges[-1]]`` receive **zero weight**
    -- they are excluded from sampling and do not contribute to any bin's count."

``neuralbench/data.py`` ``ClassificationSampler``
    "Computes balanced class weights from the training targets ... whose per-sample
    weights equal the inverse class frequency."

``neuralbench/utils.py`` ``_compute_regression_bin_weights`` / ``make_regression_bin_sampler``
    Counts are ``bincount(...).to(dtype=torch.float32)``, the weights are
    ``1.0 / counts`` in **float32** (zero for empty bins and for out-of-range
    targets), and ``WeightedRandomSampler`` receives ``weights.tolist()`` -- i.e.
    float32 values widened to float64. The normalisation constant is therefore
    exactly ``1 / count_in_bin``, rounded to float32.

``neuralbench/utils.py`` ``compute_class_weights_from_dataset`` / ``make_weighted_sampler``
    For ``task="multiclass"`` a ``(N, k>1)`` target is reduced with ``argmax(dim=-1)``,
    ``sklearn.utils.class_weight.compute_class_weight(class_weight="balanced")`` is
    evaluated over the **observed** classes only (``n_samples / (n_observed_classes *
    count_c)``, float64), the result is cast to float32, classes with no support are
    filled with ``1.0`` when some class is unobserved, and the per-sample weights are
    ``weight[y_true].tolist()``. The normalisation constant is therefore exactly
    ``N / (n_observed_classes * count_c)``, rounded to float32.

Because both helpers round through float32, the pure-float64 inverse-frequency
weights below differ from the real sampler's weights by up to one float32 ULP
(~1.2e-7 relative). The float32 rounding is replicated exactly by
:func:`native_bin_sample_weights` / :func:`native_class_sample_weights`, so the
runtime cross-check compares like with like; :func:`weights_agree_up_to_scale` still
tolerates a bounded float32 ULP scale deviation and still rejects any real bin or
weight corruption structurally (see its docstring).
"""
from __future__ import annotations

import math
import struct

# Bumped whenever the meaning of an exported array changes.
CONTRACT_VERSION = "neuralbench/sleep-special-export/1"
# The public decoder + evaluator that consume these arrays do not exist yet, so no
# array in this contract has been proven to survive the transport round trip.
CONTRACT_STATUS = "waiting_transport_validation"

REGRESSION_KIND = "regression"
CLASSIFICATION_KIND = "classification"


# --------------------------------------------------------------------------- bins


def check_bin_edges(edges):
    """Validate edges exactly as both native consumers do (>=2, strictly increasing)."""
    edges = [float(x) for x in edges]
    if len(edges) < 2:
        raise ValueError(f"bin edges must have length >= 2 to define a bin, got {edges}")
    if any(edges[i + 1] <= edges[i] for i in range(len(edges) - 1)):
        raise ValueError(f"bin edges must be strictly increasing, got {edges}")
    return edges


def assign_bin(value, edges):
    """Native bin index for ``value``, or ``None`` when it is out of range.

    Mirrors ``bucketize(t, edges[1:-1], right=True)`` together with the
    ``[edges[0], edges[-1]]`` inclusive ``in_range`` mask of ``BinnedMAE.update``.
    Out-of-range targets are *not* clamped into an end bin: they are dropped, which
    is what both ``BinnedMAE`` (via the mask) and ``RegressionBinSampler`` (via zero
    weight) do.
    """
    edges = check_bin_edges(edges)
    value = float(value)
    if math.isnan(value) or value < edges[0] or value > edges[-1]:
        return None
    # Number of inner edges <= value == bucketize(..., right=True).
    index = sum(1 for edge in edges[1:-1] if edge <= value)
    return index


def bin_counts(targets, edges):
    """Per-bin population plus the out-of-range tally, never silently discarded."""
    edges = check_bin_edges(edges)
    counts = [0] * (len(edges) - 1)
    out_of_range = 0
    for value in targets:
        index = assign_bin(value, edges)
        if index is None:
            out_of_range += 1
        else:
            counts[index] += 1
    return {"bin_edges": edges, "counts": counts, "out_of_range": out_of_range,
            "empty_bins": [i for i, n in enumerate(counts) if n == 0],
            "populated_bins": [i for i, n in enumerate(counts) if n > 0]}


def bin_sample_weights(targets, edges):
    """Inverse-frequency weight per sample; ``0.0`` for out-of-range targets.

    Proportional to the native ``RegressionBinSampler`` weighting (see the module
    docstring on the unknown normalisation constant).
    """
    summary = bin_counts(targets, edges)
    counts = summary["counts"]
    weights = []
    for value in targets:
        index = assign_bin(value, edges)
        weights.append(0.0 if index is None else 1.0 / counts[index])
    return weights


def class_counts(labels, n_classes):
    """Per-class population plus the classes with no support at all."""
    if n_classes < 1:
        raise ValueError(f"n_classes must be >= 1, got {n_classes}")
    counts = [0] * n_classes
    for label in labels:
        index = int(label)
        if not 0 <= index < n_classes:
            raise ValueError(f"class index {index} outside [0, {n_classes})")
        counts[index] += 1
    return {"counts": counts,
            "unsupported_classes": [i for i, n in enumerate(counts) if n == 0],
            "supported_classes": [i for i, n in enumerate(counts) if n > 0]}


def class_sample_weights(labels, n_classes):
    """Inverse class frequency per sample, mirroring ``ClassificationSampler``."""
    counts = class_counts(labels, n_classes)["counts"]
    return [1.0 / counts[int(label)] for label in labels]


# ------------------------------------------------- native float32 weight replication


def to_float32(value):
    """Round a Python float to the nearest float32, returned widened to float64.

    This is what ``tensor.to(dtype=torch.float32)`` followed by ``.tolist()`` does,
    and it is the only reason the native sampler weights differ from the exact
    float64 inverse frequencies below.
    """
    return struct.unpack("<f", struct.pack("<f", float(value)))[0]


def native_bin_sample_weights(targets, edges):
    """``_compute_regression_bin_weights`` reproduced in native float32 arithmetic.

    Native: ``counts = bincount(bin_idx[in_range]).to(float32)``,
    ``inv = where(counts > 0, 1.0 / counts, 0.0)`` (float32),
    ``weights[in_range] = inv[bin_idx[in_range]]`` (float32), then ``.tolist()``.

    The counts are small exact integers in float32, and a float64 reciprocal of such
    an integer is never near a float32 tie boundary for counts below 2**24, so
    rounding the float64 quotient to float32 gives the same bits as the native
    float32 division. That keeps this function pure stdlib without weakening it.
    """
    summary = bin_counts(targets, edges)
    counts = summary["counts"]
    inverse = [to_float32(1.0 / count) if count > 0 else 0.0 for count in counts]
    weights = []
    for value in targets:
        index = assign_bin(value, edges)
        weights.append(0.0 if index is None else inverse[index])
    return weights


def native_class_sample_weights(labels, n_classes):
    """``compute_class_weights_from_dataset`` weights reproduced in native float32.

    Native ``task="multiclass"`` path: ``compute_class_weight("balanced")`` over the
    **observed** classes gives ``N / (n_observed * count_c)`` in float64, ``.float()``
    rounds it to float32, and any class with no support is filled with ``1.0`` (only
    when at least one class is unobserved). Per-sample weights are ``weight[y_true]``.

    Note this is *not* plain inverse frequency: it carries the ``N / n_observed``
    factor, which is a single positive constant across every supported class, so it
    agrees with :func:`class_sample_weights` up to one scale -- exactly what
    :func:`weights_agree_up_to_scale` checks.
    """
    counts = class_counts(labels, n_classes)["counts"]
    total = sum(counts)
    if not total:
        raise ValueError("cannot derive class weights from an empty label set")
    observed = [i for i, count in enumerate(counts) if count > 0]
    per_class = [1.0] * n_classes
    for index in observed:
        per_class[index] = to_float32(total / (len(observed) * counts[index]))
    return [per_class[int(label)] for label in labels]


# One float32 ULP is ~1.19e-7 relative; the native weights reach the sampler as
# float32 values widened to float64, so a scale inferred from them can deviate by
# about that much even when every bin membership is identical. 1e-6 is a bounded
# multiple of that, and is far below any real weighting error (the smallest possible
# one -- a single sample moving between two bins of sizes n and n+1 -- changes a
# weight by 1/(n+1), i.e. >= 1e-3 relative for the populations these cases produce).
FLOAT32_SCALE_RTOL = 1e-6


def weights_agree_up_to_scale(observed, derived, rel_tol=FLOAT32_SCALE_RTOL):
    """Compare a native sampler's weights with derived ones up to one positive factor.

    The native normalisation constant *is* known (see the module docstring): it is
    ``1 / count_in_bin`` for the regression sampler and ``N / (n_observed * count_c)``
    for the classification sampler. Comparing up to a single positive scale therefore
    still pins the per-sample *ratios*, which is the whole scientific content of the
    weighting, while remaining agnostic about that constant.

    The tolerance is a bounded float32 ULP allowance, not a loosened rule, and it is
    backed by two exact structural checks that no bin/class corruption can pass:

    * the zero-weight sample sets must match exactly, and
    * samples sharing a derived weight must share one identical observed weight, and
      distinct derived weights must map to distinct observed weights.

    The second check is exact float64 equality on the native values, so a sample
    placed in the wrong bin, two bins merged, or a corrupted count are all rejected
    regardless of ``rel_tol``. Pass native-dtype derived weights (see
    :func:`native_bin_sample_weights`) to make the comparison float32-exact.

    Returns a diagnostic dict rather than a bare bool: a mismatch has to be
    reportable, and the inferred ``scale`` records the native normalisation constant.
    """
    observed, derived = [float(x) for x in observed], [float(x) for x in derived]
    if len(observed) != len(derived):
        return {"agree": False, "reason": "length mismatch",
                "observed_len": len(observed), "derived_len": len(derived)}
    zero_disagreements = [i for i, (o, d) in enumerate(zip(observed, derived))
                          if (o == 0.0) != (d == 0.0)]
    if zero_disagreements:
        return {"agree": False, "reason": "zero-weight sample sets differ",
                "first_disagreeing_indices": zero_disagreements[:8],
                "zero_disagreement_count": len(zero_disagreements)}
    grouping = _weight_grouping(observed, derived, rel_tol)
    if grouping is not None:
        return grouping
    scales = [o / d for o, d in zip(observed, derived) if d != 0.0]
    if not scales:
        return {"agree": True, "scale": None, "reason": "every derived weight is zero"}
    scale = scales[0]
    if scale <= 0.0 or not math.isfinite(scale):
        return {"agree": False, "reason": "non-positive or non-finite scale", "scale": scale}
    worst = max(abs(s - scale) / scale for s in scales)
    return {"agree": worst <= rel_tol, "scale": scale, "max_relative_deviation": worst,
            "compared_samples": len(scales), "rel_tol": rel_tol,
            "exact_scale_match": worst == 0.0,
            "tolerance_basis": "bounded float32 ULP of the native weights.tolist() "
                               "round trip; structural bin/class membership is checked "
                               "by exact equality, not by this tolerance"}


def _weight_grouping(observed, derived, rel_tol):
    """Exact membership check; returns a failure dict, or ``None`` when consistent.

    Two samples in the same native bin receive the same weight *bits*, so equal
    derived weights must mean identical observed weights -- that is checked with
    exact equality. The converse (distinct derived weights collapsing onto one
    observed weight) is only a defect when the derived weights differ by more than
    the same bounded tolerance, so two very large bins whose float32 reciprocals
    happen to coincide are not reported as a merge.
    """
    by_derived = {}
    seen_observed = {}
    for position, (o, d) in enumerate(zip(observed, derived)):
        if d in by_derived:
            first, value = by_derived[d]
            if o != value:
                return {"agree": False,
                        "reason": "samples with equal derived weight have different "
                                  "native weights (bin/class membership differs)",
                        "derived_weight": d, "native_weights": [value, o],
                        "sample_indices": [first, position]}
            continue
        if o in seen_observed:
            first, previous = seen_observed[o]
            spread = abs(previous - d) / max(abs(previous), abs(d))
            if spread > rel_tol:
                return {"agree": False,
                        "reason": "distinct derived weights share one native weight "
                                  "(bins/classes merged)",
                        "derived_weights": [previous, d], "native_weight": o,
                        "relative_spread": spread,
                        "sample_indices": [first, position]}
            continue
        by_derived[d] = (position, o)
        seen_observed[o] = (position, d)
    return None


# ------------------------------------------------------------------------ metrics


def binned_mae(predictions, targets, edges):
    """Independent ``BinnedMAE``: mean of per-bin MAEs over non-empty bins.

    Returns ``value=None`` when every bin is empty, which is what the native metric
    signals with NaN. Empty and out-of-range populations are reported, never filled
    in and never rebalanced.
    """
    edges = check_bin_edges(edges)
    n_bins = len(edges) - 1
    sums, counts = [0.0] * n_bins, [0] * n_bins
    out_of_range = 0
    for prediction, target in zip(predictions, targets):
        index = assign_bin(target, edges)
        if index is None:
            out_of_range += 1
            continue
        sums[index] += abs(float(prediction) - float(target))
        counts[index] += 1
    per_bin = [sums[i] / counts[i] if counts[i] else None for i in range(n_bins)]
    populated = [value for value in per_bin if value is not None]
    return {"value": sum(populated) / len(populated) if populated else None,
            "per_bin_mae": per_bin, "bin_counts": counts, "bin_edges": edges,
            "empty_bins": [i for i, n in enumerate(counts) if n == 0],
            "out_of_range": out_of_range,
            "averaged_over_bins": len(populated)}


def balanced_accuracy(predicted, targets, n_classes):
    """Independent macro-averaged recall, with both zero-support conventions.

    ``torchmetrics`` multiclass ``Accuracy(average="macro")`` averages per-class
    recall; how it treats a class with **no support** is version dependent, so both
    candidate values are returned and the caller reports which one the native metric
    matched instead of asserting a convention.
    """
    counts = class_counts(targets, n_classes)
    correct = [0] * n_classes
    for prediction, target in zip(predicted, targets):
        if int(prediction) == int(target):
            correct[int(target)] += 1
    recalls = [correct[i] / counts["counts"][i] if counts["counts"][i] else None
               for i in range(n_classes)]
    supported = [value for value in recalls if value is not None]
    return {"over_supported_classes": sum(supported) / len(supported) if supported else None,
            "over_all_classes_zero_for_unsupported": sum(v or 0.0 for v in recalls) / n_classes,
            "per_class_recall": recalls, "class_counts": counts["counts"],
            "unsupported_classes": counts["unsupported_classes"]}


def mean_absolute_error(predictions, targets):
    values = [abs(float(p) - float(t)) for p, t in zip(predictions, targets)]
    return sum(values) / len(values) if values else None


def root_mean_squared_error(predictions, targets):
    values = [(float(p) - float(t)) ** 2 for p, t in zip(predictions, targets)]
    return math.sqrt(sum(values) / len(values)) if values else None


# --------------------------------------------------------- exported target checks


def classify_target_rows(rows, n_classes):
    """Describe what the native classification target actually is; never reduce it.

    The ``sleep_arousal`` target is a ``LabelEncoder`` with ``return_one_hot: true``
    **and** ``aggregation: sum``, so a 15 s window covering several ``SleepArousal``
    events can plausibly carry a summed count vector (e.g. ``[2, 0]``) rather than a
    one-hot row. The caller must know which it is before building any Agent-side
    label array, so this returns a verdict plus the evidence; deciding to argmax,
    clip or renormalise a non-one-hot row would silently invent a label rule that the
    pinned source never specifies.
    """
    verdict = {"kind": None, "rows": len(rows), "n_classes": n_classes,
               "row_sum_histogram": {}, "distinct_values": set(),
               "negative_rows": [], "non_integer_rows": [], "wrong_width_rows": [],
               "all_zero_rows": 0, "multi_hot_rows": 0, "count_rows": 0}
    for position, row in enumerate(rows):
        values = [float(x) for x in row]
        if len(values) != n_classes:
            verdict["wrong_width_rows"].append(position)
            continue
        verdict["distinct_values"].update(values)
        if any(value < 0.0 for value in values):
            verdict["negative_rows"].append(position)
        if any(value != int(value) for value in values):
            verdict["non_integer_rows"].append(position)
        total = sum(values)
        key = repr(round(total, 6))
        verdict["row_sum_histogram"][key] = verdict["row_sum_histogram"].get(key, 0) + 1
        nonzero = sum(1 for value in values if value != 0.0)
        if nonzero == 0:
            verdict["all_zero_rows"] += 1
        elif nonzero > 1:
            verdict["multi_hot_rows"] += 1
        if any(value not in (0.0, 1.0) for value in values):
            verdict["count_rows"] += 1
    verdict["distinct_values"] = sorted(verdict["distinct_values"])
    strict_one_hot = (
        not verdict["wrong_width_rows"] and not verdict["negative_rows"]
        and not verdict["non_integer_rows"] and not verdict["all_zero_rows"]
        and not verdict["multi_hot_rows"] and not verdict["count_rows"]
    )
    if verdict["wrong_width_rows"]:
        verdict["kind"] = "invalid_width"
    elif strict_one_hot:
        verdict["kind"] = "strict_one_hot"
    elif verdict["negative_rows"] or verdict["non_integer_rows"]:
        verdict["kind"] = "unexpected_values"
    else:
        verdict["kind"] = "non_negative_count_vector"
    verdict["strict_one_hot"] = strict_one_hot
    return verdict


def one_hot_to_index(rows, n_classes):
    """Class indices for **strictly** one-hot rows; raises with a diagnostic otherwise."""
    verdict = classify_target_rows(rows, n_classes)
    if not verdict["strict_one_hot"]:
        raise ValueError(
            "Native classification target is not strictly one-hot, so no class index "
            "can be derived without inventing a reduction rule the pinned source does "
            f"not define. Observed contract: {verdict}")
    return [max(range(n_classes), key=lambda i: float(row[i])) for row in rows]


def _as_row(row):
    """One label row as a list of floats; a bare scalar counts as a width-1 row.

    ``np.ndarray.tolist()`` gives scalars for a ``(N,)`` array and lists for ``(N, k)``,
    so both shapes have to be readable without reshaping the caller's array.
    """
    try:
        return [float(x) for x in row]
    except TypeError:
        return [float(row)]


def class_index_form(rows, n_classes, max_distinct=16):
    """Read a native label array **without** inventing a reduction rule.

    Two forms are accepted, and only these two:

    ``strict_one_hot``
        every row has width ``n_classes``, is non-negative, integral, and holds
        exactly one ``1.0`` -- the exported ``LabelEncoder(return_one_hot=true)`` form.
        Indices come from :func:`one_hot_to_index`, which re-validates strictly.
    ``integer_labels``
        every row has width ``1`` and holds a non-negative integer in
        ``[0, n_classes)`` -- the form the native classifier emits in
        ``exp.test_predictions()``. A flat ``(N,)`` array (the same labels without the
        trailing singleton column) is read as width-1 rows, so ``N`` and ``N x 1`` are
        treated identically without reshaping or reordering anything.

    Anything else (summed count vectors, multi-hot rows, all-zero rows, fractional
    or negative values, wrong widths) returns ``form=None`` with the evidence. The
    caller must report that rather than argmax/clip/renormalise it: deciding how to
    collapse an ambiguous row would silently invent a label rule the pinned source
    never specifies.
    """
    rows = [_as_row(row) for row in rows]
    widths = sorted({len(row) for row in rows})
    values = sorted({value for row in rows for value in row})
    evidence = {
        "rows": len(rows), "widths": widths, "n_classes": n_classes,
        "distinct_values": values[:max_distinct],
        "distinct_values_truncated": len(values) > max_distinct,
        "target_contract": None,
    }
    if rows and widths == [n_classes]:
        verdict = classify_target_rows(rows, n_classes)
        evidence["target_contract"] = verdict
        if verdict["strict_one_hot"]:
            return {"form": "strict_one_hot",
                    "indices": one_hot_to_index(rows, n_classes), "evidence": evidence}
    if rows and widths == [1]:
        single = [row[0] for row in rows]
        integral = [value for value in single
                    if value == int(value) and 0 <= value < n_classes]
        evidence["integer_labels_valid"] = len(integral) == len(single)
        if len(integral) == len(single):
            return {"form": "integer_labels", "indices": [int(value) for value in single],
                    "evidence": evidence}
    return {"form": None, "indices": None, "evidence": evidence}


def align_native_test_labels(native_truth_rows, exported_rows, n_classes,
                             truth_shape=None, exported_shape=None):
    """Match the native test labels against the exported private label rows exactly.

    ``exp.test_predictions()`` carries whatever the native classifier emits -- integer
    labels, shape ``(N, 1)`` or ``(N,)`` -- while the exported ``test-labels.npy`` is
    the native target verbatim, i.e. ``(N, n_classes)`` one-hot. Reconciling those two
    is legitimate *only* when both sides are in a validated form and agree per row in
    the original order, so this returns a diagnostic dict with both shapes, both forms
    and both evidence blocks, and ``aligned: False`` for every other case. Nothing is
    summed, argmaxed or reordered here.
    """
    native = class_index_form(native_truth_rows, n_classes)
    exported = class_index_form(exported_rows, n_classes)
    result = {
        "aligned": False, "n_classes": n_classes,
        "native_form": native["form"], "exported_form": exported["form"],
        "native_shape": None if truth_shape is None else list(truth_shape),
        "exported_shape": None if exported_shape is None else list(exported_shape),
        "native_rows": len(native_truth_rows), "exported_rows": len(exported_rows),
        "native_evidence": native["evidence"],
        "exported_evidence": exported["evidence"],
        "reduction_applied": None,
    }
    if not native_truth_rows or not exported_rows:
        result["reason"] = "one of the two label arrays is empty, so nothing can be aligned"
        return result
    if exported["form"] is None:
        result["reason"] = ("the exported private labels are not in a validated label "
                            "form, so no class index can be derived from them")
        return result
    if native["form"] is None:
        result["reason"] = ("the native test targets are not in a validated label form, "
                            "so they cannot be matched against the exported labels")
        return result
    if len(native["indices"]) != len(exported["indices"]):
        result["reason"] = "row count mismatch between native and exported labels"
        return result
    mismatches = [i for i, (a, b) in enumerate(zip(native["indices"], exported["indices"]))
                  if a != b]
    if mismatches:
        result.update(
            reason="per-row label mismatch (value or order)",
            mismatch_count=len(mismatches), first_mismatch_indices=mismatches[:8],
            first_mismatches=[{"row": i, "native": native["indices"][i],
                               "exported": exported["indices"][i]}
                              for i in mismatches[:8]])
        return result
    result.update(
        aligned=True, reason=None, order_preserved=True,
        labels=exported["indices"],
        native_labels_match_exported_exactly=True,
        reduction_applied=("strict one-hot validated and converted to its unique class "
                           "index" if exported["form"] == "strict_one_hot" else
                           "validated integer labels used as-is"),
        note=("Both sides were validated independently; rows are compared in the "
              "original order and must agree one by one. The one-hot arrays themselves "
              "are left untouched on disk for a future training transport."))
    return result


# ------------------------------------------------------------- contract documents


def regression_export_contract(bin_edges, cap_s, n_outputs=1):
    """Arrays a later frozen-array backend needs to reproduce native onset training."""
    return {
        "contract_version": CONTRACT_VERSION, "status": CONTRACT_STATUS,
        "target_kind": REGRESSION_KIND, "n_outputs": n_outputs,
        "public_arrays": {
            "x": "float32 (N, C, T) native `batch.data['neuro']`, split order preserved",
            "y": f"float32 (N, {n_outputs}) native SleepOnsetTargetExtractor value, "
                 f"clip(n2_onset - segment.stop, 0, {cap_s})",
            "bin_index": "int16 (N,) native BinnedMAE/RegressionBinSampler bin, -1 when "
                         "the target is outside [bin_edges[0], bin_edges[-1]]",
            "sample_weight": "float64 (N,) inverse-frequency weight of this split's own "
                             "bins; 0.0 for out-of-range targets. Proportional to the "
                             "native RegressionBinSampler weighting, whose normalisation "
                             "constant is exactly 1/count_in_bin (see "
                             "native_bin_sample_weights for the float32-exact form)",
        },
        "auxiliary_provenance": (
            "bin_index and sample_weight for a split are computed only from that "
            "split's own public targets. The test split never contributes to any "
            "public array, and its labels stay in evaluator-private/."),
        "sampler": {
            "name": "RegressionBinSampler", "bin_edges": list(bin_edges),
            "applies_to": "train only (native Data.prepare builds a sampler for the "
                          "train DataLoader; val/test iterate in order)",
            "val_weights_note": "val bin_index/sample_weight are exported as diagnostics "
                                "only; native training never samples the val split.",
            "normalisation": "1 / count_in_bin, rounded to float32 by "
                             "_compute_regression_bin_weights before weights.tolist()",
        },
        "loss": {"name": "MultiLoss", "losses": {"mse": "MSELoss"}, "weights": {"mse": 0.0001},
                 "note": "Weighted MultiLoss must be reproduced, not replaced by a bare MSE: "
                         "the 1e-4 weight is what keeps gradient clipping from saturating."},
        "primary_metric": {"log_name": "bmae", "name": "BinnedMAE", "mode": "min",
                           "monitor": "val/bmae", "bin_boundaries": list(bin_edges)},
        "unsupported_bin_policy": (
            "Empty bins and out-of-range targets are reported as-is. No class/bin "
            "coverage is forced, no target value is resampled, clipped or synthesised."),
    }


def classification_export_contract(n_classes, mapping, aggregation):
    """Arrays for the arousal case, pending the real target-shape probe."""
    return {
        "contract_version": CONTRACT_VERSION, "status": CONTRACT_STATUS,
        "target_kind": CLASSIFICATION_KIND, "n_classes": n_classes,
        "public_arrays": {
            "x": "float32 (N, C, T) native `batch.data['neuro']`, split order preserved",
            "y": f"native `batch.data['target']` verbatim, expected (N, {n_classes}); "
                 "NOT reduced to a label index here",
            "sample_weight": "float64 (N,) inverse class frequency of this split's own "
                             "targets -- present only when the native target is verified "
                             "strictly one-hot; absent otherwise. Native "
                             "compute_class_weights_from_dataset('balanced') normalises "
                             "it as N/(n_observed_classes * count_c) in float32, a single "
                             "positive constant across supported classes",
        },
        "target_contract_probe_required": True,
        "target_contract_note": (
            f"LabelEncoder(predefined_mapping={mapping}, return_one_hot=true, "
            f"aggregation={aggregation!r}, treat_missing_as_separate_class=true). Summing "
            "one-hot rows over the SleepArousal events inside a 15 s window can yield a "
            "count vector rather than a one-hot row. The exporter probes the real array "
            "and fails with the observed histogram rather than applying a custom reduce."),
        "sampler": {"name": "ClassificationSampler", "applies_to": "train only"},
        "loss": {"name": "CrossEntropyLoss"},
        "primary_metric": {"log_name": "bal_acc", "name": "Accuracy", "mode": "max",
                           "monitor": "val/bal_acc", "average": "macro",
                           "note": "The native task metric is balanced accuracy. The "
                                   "official PhysioNet/CinC 2018 challenge scorer (gross "
                                   "AUPRC over arousal samples) is a different quantity "
                                   "and is NOT computed or claimed here."},
        "unsupported_class_policy": (
            "Classes with no support in a split are reported. No split is rebalanced and "
            "no label is invented to obtain coverage."),
    }
