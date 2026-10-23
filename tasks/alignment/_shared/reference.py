"""Maintainer synthetic oracle: augmented least squares, independent of submission solver."""
import numpy as np
from contract import correlations, load_packet, write_outputs


def compute(packet):
    index = {sid: i for i, sid in enumerate(packet['ids'])}
    predictions, scores = [], []
    for fold in packet['folds']:
        train, test = ([index[sid] for sid in fold[key]] for key in ['train_ids', 'test_ids'])
        x, y = packet['x'][train], packet['y'][train]
        # Intercept is unpenalized; ridge represented by synthetic rows.
        design = np.column_stack([np.ones(len(train)), x])
        penalty = np.diag([0.0] + [np.sqrt(0.7)] * x.shape[1])
        coef = np.linalg.lstsq(np.vstack([design, penalty]),
                             np.vstack([y, np.zeros((x.shape[1] + 1, y.shape[1]))]), rcond=None)[0]
        pred = np.column_stack([np.ones(len(test)), packet['x'][test]]) @ coef
        predictions.append(pred)
        scores.append(correlations(pred, packet['y'][test]))
    return predictions, np.array(scores)


def run(inputs, output):
    packet = load_packet(inputs)
    write_outputs(packet, output, *compute(packet))
