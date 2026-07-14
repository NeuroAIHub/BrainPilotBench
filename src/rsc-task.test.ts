import { test } from "node:test";
import assert from "node:assert/strict";
import {
  existsSync, mkdtempSync, mkdirSync, readFileSync, rmSync, symlinkSync, writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { execFileSync, spawnSync } from "node:child_process";

const TASK_DIR = join(process.cwd(), "tasks", "neuro-rsc-place-cell");
const SETUP = join(TASK_DIR, "env", "setup.sh");
const BENCHMARK = join(TASK_DIR, "checks", "benchmark.py");
const CHECK = join(TASK_DIR, "checks", "check.sh");
const DATA_SHA = "0a5f35ccf29ce6611908f5233b4325bfcc43e63c57e4d3763a4cf7dcea6f0987";
const PYTHON = process.env.BPB_TEST_PYTHON ?? "python3";

test("RSC setup stages only public Agent inputs", () => {
  const root = mkdtempSync(join(tmpdir(), "bpb-rsc-setup-"));
  try {
    const xdg = join(root, "cache");
    const cached = join(xdg, "brainpilot-bench", DATA_SHA);
    const workspace = join(root, "workspace");
    mkdirSync(cached, { recursive: true });
    mkdirSync(workspace);
    writeFileSync(join(cached, "data"), "synthetic mat placeholder");

    execFileSync("/bin/bash", [SETUP], {
      cwd: workspace,
      env: { ...process.env, XDG_CACHE_HOME: xdg },
      stdio: "pipe",
    });

    assert.ok(existsSync(join(workspace, "data", "VRBeltReframe.mat")));
    const schema = join(workspace, "checks", "output_schema.json");
    assert.ok(existsSync(schema));
    assert.match(readFileSync(schema, "utf8"), /benchmark_summary\.json/);
    assert.equal(existsSync(join(workspace, "checks", "reference.json")), false);
    assert.equal(existsSync(join(workspace, "checks", "check.sh")), false);
    assert.equal(existsSync(join(workspace, "checks", "benchmark.py")), false);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("RSC scorer computes the frozen aggregate and rejects implicit JSON coercion", () => {
  const root = mkdtempSync(join(tmpdir(), "bpb-rsc-check-"));
  try {
    mkdirSync(join(root, "artifacts"));
    const summary = {
      cross_session_place_cell_stability: { place_cell_ratio_mean: 0.3862502045956126 },
      position_decoding_significance: {
        real_median_decoding_error_cm: 8,
        shuffle_median_decoding_error_cm: 20,
        decoding_significant: true,
      },
    };
    const summaryPath = join(root, "artifacts", "benchmark_summary.json");
    writeFileSync(summaryPath, JSON.stringify(summary));

    const accepted = spawnSync("/bin/bash", [CHECK], { cwd: root, encoding: "utf8" });
    assert.equal(accepted.status, 0, accepted.stderr);
    assert.match(accepted.stdout, /"score": 1(?:\.0)?/);

    summary.position_decoding_significance.decoding_significant = "false" as unknown as boolean;
    writeFileSync(summaryPath, JSON.stringify(summary));
    const rejected = spawnSync("/bin/bash", [CHECK], { cwd: root, encoding: "utf8" });
    assert.equal(rejected.status, 0, rejected.stderr);
    assert.doesNotMatch(rejected.stdout, /BPB_SCORES/);
    assert.match(rejected.stderr, /must be a JSON boolean/);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("RSC reference accepts a typed symlink to an extensionless content-cache file", (t) => {
  const dependencies = spawnSync(PYTHON, ["-c", "import numpy, scipy, sklearn"], {
    encoding: "utf8",
  });
  if (dependencies.status !== 0) {
    t.skip(`RSC Python dependencies are unavailable for ${PYTHON}`);
    return;
  }

  const root = mkdtempSync(join(tmpdir(), "bpb-rsc-reference-"));
  try {
    const target = join(root, "data");
    const input = join(root, "synthetic-session.npz");
    const output = join(root, "output");
    const seed = spawnSync(PYTHON, ["-c", [
      "import numpy as np, sys",
      "target = sys.argv[1]",
      "trials = np.repeat(np.arange(1, 11), 20)",
      "position = np.tile(np.linspace(0.0, 1.0, 20), 10)",
      "timestamps = np.arange(position.size, dtype=float) / 10.0",
      "centers = np.linspace(0.1, 0.9, 5)[:, None]",
      "neural = np.exp(-((position[None, :] - centers) ** 2) / 0.02)",
      "with open(target, 'wb') as handle:",
      "    np.savez(handle, neural_activity=neural, position_norm=position, trial_id=trials, timestamps_s=timestamps)",
    ].join("\n"), target], { encoding: "utf8" });
    assert.equal(seed.status, 0, seed.stderr);
    symlinkSync(target, input);

    const result = spawnSync(PYTHON, [BENCHMARK,
      "--input", input,
      "--output", output,
      "--n-bins", "10",
      "--place-shuffles", "2",
      "--decoding-shuffles", "2",
      "--cv-folds", "5",
      "--seed", "7",
    ], { encoding: "utf8", timeout: 30_000 });

    assert.equal(result.status, 0, `${result.stdout}\n${result.stderr}`);
    assert.doesNotMatch(result.stderr, /RuntimeWarning/);
    assert.ok(existsSync(join(output, "benchmark_summary.json")));
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
