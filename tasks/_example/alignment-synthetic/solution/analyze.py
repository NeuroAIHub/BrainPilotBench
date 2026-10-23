"""Reference submission for synthetic-ridge-v1 only; all numbers computed from inputs."""
import argparse
import numpy as np
from alignment_contract import correlations, load_packet, write_outputs


def analyze(inputs, output):
    packet = load_packet(inputs)
    index = {sid: i for i, sid in enumerate(packet['ids'])}
    predictions, scores = [], []
    for fold in packet['folds']:
        train = [index[sid] for sid in fold['train_ids']]
        test = [index[sid] for sid in fold['test_ids']]
        x, y = packet['x'][train], packet['y'][train]
        xm, ym = x.mean(0), y.mean(0)
        xc, yc = x - xm, y - ym
        weights = np.linalg.solve(xc.T @ xc + 0.7 * np.eye(x.shape[1]), xc.T @ yc)
        pred = (packet['x'][test] - xm) @ weights + ym
        predictions.append(pred)
        scores.append(correlations(pred, packet['y'][test]))
    write_outputs(packet, output, predictions, np.array(scores))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--inputs', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    analyze(args.inputs, args.output)
