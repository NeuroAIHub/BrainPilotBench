import unittest

import numpy as np

from calms_metrics import CLASSIC_VOCAB, NEW_BEHAVIORS, score_sequences, score_task2, score_task3


def probabilities(labels, n_classes):
    return np.eye(n_classes, dtype=np.float64)[labels]


class MetricContractTests(unittest.TestCase):
    def test_other_frames_count_as_attack_false_positives(self):
        truth = {"a": np.array([0, 3, 1, 2])}
        scores = {"a": probabilities([0, 0, 1, 2], 4)}
        result = score_sequences(truth, scores, task="task1", vocab=CLASSIC_VOCAB)
        self.assertAlmostEqual(result["f1_by_class"]["attack"], 2 / 3)
        self.assertAlmostEqual(result["f1"], 8 / 9)

    def test_other_prediction_causes_scored_class_false_negative(self):
        truth = {"a": np.array([0, 1, 2, 3])}
        scores = {"a": probabilities([3, 1, 2, 3], 4)}
        result = score_sequences(truth, scores, task="task1", vocab=CLASSIC_VOCAB)
        self.assertEqual(result["f1_by_class"]["attack"], 0)
        self.assertAlmostEqual(result["f1"], 2 / 3)

    def test_missing_or_bad_scores_fail(self):
        truth = {"a": np.array([3])}
        with self.assertRaisesRegex(ValueError, "sequence"):
            score_sequences(truth, {}, task="task1", vocab=CLASSIC_VOCAB)
        with self.assertRaisesRegex(ValueError, "finite"):
            score_sequences(truth, {"a": np.array([[np.nan, 0, 0, 1]])}, task="task1", vocab=CLASSIC_VOCAB)
        with self.assertRaisesRegex(ValueError, "sum to one"):
            score_sequences(truth, {"a": np.array([[0.1, 0.1, 0.1, 0.1]])}, task="task1", vocab=CLASSIC_VOCAB)
        with self.assertRaisesRegex(ValueError, "shape"):
            score_sequences(truth, {"a": np.array([[0.0, 1.0]])}, task="task1", vocab=CLASSIC_VOCAB)

    def test_task2_requires_all_five_independent_groups(self):
        groups = {f"annotator-id_{i}": {"s": np.array([0, 1, 2, 3])} for i in range(1, 6)}
        scores = {group: {"s": probabilities([0, 1, 2, 3], 4)} for group in groups}
        vocabs = {group: CLASSIC_VOCAB for group in groups}
        self.assertEqual(score_task2(groups, scores, vocabs)["f1"], 1)
        scores["annotator-id_1"] = {"s": probabilities([3, 3, 3, 3], 4)}
        self.assertAlmostEqual(score_task2(groups, scores, vocabs)["f1"], 4 / 5)
        del scores["annotator-id_5"]
        with self.assertRaisesRegex(ValueError, "annotator group"):
            score_task2(groups, scores, vocabs)

    def test_task3_requires_seven_binary_vocabs(self):
        truth = {name: {"s": np.array([0, 1])} for name in NEW_BEHAVIORS}
        scores = {name: {"s": probabilities([0, 1], 2)} for name in NEW_BEHAVIORS}
        vocab = {name: {"other": 0, name: 1} for name in NEW_BEHAVIORS}
        self.assertEqual(score_task3(truth, scores, vocab)["f1"], 1)
        scores["groom"] = {"s": probabilities([0, 0], 2)}
        self.assertAlmostEqual(score_task3(truth, scores, vocab)["f1"], 6 / 7)
        vocab["groom"] = {"other": 0, "groom": 2}
        with self.assertRaisesRegex(ValueError, "mapping"):
            score_task3(truth, scores, vocab)


if __name__ == "__main__":
    unittest.main()
