import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { isAbsolute, join, relative } from "node:path";
import test from "node:test";
import type { ExecSandbox, ExecRequest, ExecResult } from "./sandbox.js";
import type { Task } from "./task.js";
import type { RunBundle } from "./score.js";
import { cachePathFor } from "./data/cache.js";
import { prepareEvaluatorData } from "./evaluator.js";
import { runPrivateScorer } from "./private-score.js";

const REVISION = "a".repeat(40);
const REPO = "BrainPilot-Bench/Tasks-Data-Private";
const SCORED_AT = "2026-10-19T00:00:00.000Z";
const hash = (value: Buffer | string) => createHash("sha256").update(value).digest("hex");
const sentinel = (metrics: string) => `>>>>> BPB_SCORES\n${metrics}\n<<<<< BPB_SCORES\n`;

function fixture() {
  const base = realpathSync(mkdtempSync(join(tmpdir(), "bpb-private-score-test-")));
  const taskDir = join(base, "tasks", "eeg", "fixture-task");
  const evaluatorRoot = join(base, "owner", "evaluator");
  const privateCache = join(base, "private-cache");
  const bundleDir = join(base, "bundle");
  const artifacts = join(bundleDir, "artifacts");
  const toolDir = join(base, "_shared", "evaluator");
  for (const dir of [taskDir, join(base, "owner"), artifacts, toolDir])
    mkdirSync(dir, { recursive: true, mode: 0o700 });
  writeFileSync(join(toolDir, "score.py"), "# mocked by ExecSandbox\n");
  const privateBody = Buffer.from("opaque fixture Test bytes\n");
  const name = "evaluator__test__labels.bin";
  const entry = {
    name, scope: "private" as const,
    uri: `hf://datasets/${REPO}@${REVISION}/tasks/eeg/fixture-task/evaluator/test/labels.bin`,
    sha256: hash(privateBody), bytes: privateBody.length, format: "bin",
  };
  const lock = { schema: "bpb-evaluator-data/1", task_id: "fixture-task", repo_id: REPO,
    revision: REVISION, files: [{ name, path: "test/labels.bin", sha256: entry.sha256, bytes: entry.bytes }] };
  writeFileSync(join(taskDir, "evaluator.lock"), JSON.stringify(lock));
  const task: Task = {
    meta: { id: "fixture-task", domain: "eeg", summary: "fixture", expectedArtifacts: [
      { workspace: "prediction.json" }], timeoutMin: 5, budgetTokens: 100, requires: {},
      version: "protocol-1", evaluation: { primaryMetric: { id: "accuracy", direction: "maximize" } },
    },
    turns: [{ send: "fixture" }], askUser: {}, rubric: { dimensions: ["correctness"] },
    scorers: [{ kind: "exec-script", timeout_min: 2 }], datasets: [entry], dir: taskDir,
  };
  const prediction = '{"predictions":[1,0]}\n';
  writeFileSync(join(artifacts, "prediction.json"), prediction);
  mkdirSync(join(artifacts, "nested"));
  writeFileSync(join(artifacts, "nested", "notes.txt"), "submitted notes\n");
  writeFileSync(join(artifacts, ".hidden"), "submitted hidden file\n");
  writeFileSync(join(bundleDir, "meta.json"), JSON.stringify({ taskId: task.meta.id,
    agent: "fixture-agent", taskVersion: task.meta.version }));
  const publicScores = '{"state":"public-scored","accuracy":0.1}\n';
  writeFileSync(join(bundleDir, "scores.json"), publicScores);
  const bundle: RunBundle = { runDir: bundleDir, runId: "fixture-run", version: "fixture-agent",
    events: [], signals: { completed: true } };
  const setup = async () => {
    const source = cachePathFor(entry.sha256, privateCache);
    mkdirSync(join(privateCache, entry.sha256), { recursive: true, mode: 0o700 });
    writeFileSync(source, privateBody, { mode: 0o600 });
    await prepareEvaluatorData(task, evaluatorRoot, { cacheRoot: privateCache });
  };
  return { base, taskDir, evaluatorRoot, privateCache, bundleDir, artifacts, privateBody,
    task, bundle, prediction, publicScores, setup,
    cleanup: () => rmSync(base, { recursive: true, force: true }) };
}

function withDocker<T>(run: () => Promise<T>): Promise<T> {
  const previous = { isolation: process.env.BPB_SUBMISSION_ISOLATION, image: process.env.BPB_INFERENCE_IMAGE };
  process.env.BPB_SUBMISSION_ISOLATION = "docker";
  process.env.BPB_INFERENCE_IMAGE = `fixture@sha256:${"a".repeat(64)}`;
  return run().finally(() => {
    if (previous.isolation === undefined) delete process.env.BPB_SUBMISSION_ISOLATION;
    else process.env.BPB_SUBMISSION_ISOLATION = previous.isolation;
    if (previous.image === undefined) delete process.env.BPB_INFERENCE_IMAGE;
    else process.env.BPB_INFERENCE_IMAGE = previous.image;
  });
}

function sandbox(run: (req: ExecRequest) => ExecResult | Promise<ExecResult>): ExecSandbox {
  return { run: async (req) => run(req) };
}

const result = (stdout: string, exitCode = 0, timedOut = false): ExecResult =>
  ({ stdout, stderr: "", exitCode, timedOut });

test("private scorer receives a complete frozen artifact manifest outside the bundle", async () => {
  const f = fixture();
  try {
    await f.setup();
    await withDocker(async () => {
      const out = await runPrivateScorer(f.task, f.bundle, SCORED_AT, { evaluatorRoot: f.evaluatorRoot,
        sandbox: sandbox((request) => {
          assert.equal(request.cwd.startsWith(f.bundleDir), false);
          assert.equal(request.cwd.startsWith(f.evaluatorRoot), false);
          assert.equal(request.args?.includes(f.evaluatorRoot), true);
          assert.equal(request.args?.includes(f.artifacts), true);
          const freezePath = request.args?.at(-1);
          assert.ok(freezePath && isAbsolute(freezePath));
          assert.equal(relative(f.bundleDir, freezePath).startsWith(".."), true);
          const freeze = JSON.parse(readFileSync(freezePath, "utf8"));
          assert.equal(freeze.schema, "bpb-private-submission-freeze/1");
          assert.equal(freeze.task_id, f.task.meta.id);
          assert.equal(freeze.task_version, f.task.meta.version);
          assert.deepEqual(freeze.files, {
            ".hidden": hash("submitted hidden file\n"),
            "nested/notes.txt": hash("submitted notes\n"),
            "prediction.json": hash(f.prediction),
          });
          assert.equal(existsSync(join(f.bundleDir, "test", "labels.bin")), false);
          return result(sentinel('{"accuracy":0.75,"loss":0.25}'));
        }),
      });
      assert.equal(out.state, "scored");
      assert.equal(out.evaluationScope, "independent-evaluator-test");
      assert.equal(out.dataRevision, REVISION);
      assert.equal(out.primaryMetric?.id, "accuracy");
      assert.deepEqual(out.results.map((item) => item.value), [{ accuracy: 0.75, loss: 0.25 }]);
      assert.match(out.submissionFreezeSha256 ?? "", /^[a-f0-9]{64}$/);
      assert.equal(readFileSync(join(f.bundleDir, "scores.json"), "utf8"), f.publicScores);
      assert.equal(existsSync(join(f.bundleDir, "scores.private.json")), false);
      assert.equal(readFileSync(join(f.artifacts, "prediction.json"), "utf8"), f.prediction);
    });
  } finally { f.cleanup(); }
});

test("private scorer discards a score if submitted artifacts change", async () => {
  const f = fixture();
  try {
    await f.setup();
    await withDocker(async () => {
      await assert.rejects(runPrivateScorer(f.task, f.bundle, SCORED_AT, { evaluatorRoot: f.evaluatorRoot,
        sandbox: sandbox(() => {
          writeFileSync(join(f.artifacts, "prediction.json"), "changed\n");
          return result(sentinel('{"accuracy":0.9}'));
        }),
      }), /artifacts changed|submission .*changed/);
      assert.equal(readFileSync(join(f.bundleDir, "scores.json"), "utf8"), f.publicScores);
    });
  } finally { f.cleanup(); }
});

test("private scorer rejects a new root file written into the submission bundle", async () => {
  const f = fixture();
  try {
    await f.setup();
    await withDocker(async () => {
      await assert.rejects(runPrivateScorer(f.task, f.bundle, SCORED_AT, { evaluatorRoot: f.evaluatorRoot,
        sandbox: sandbox(() => {
          writeFileSync(join(f.bundleDir, "private-leak.bin"), f.privateBody);
          return result(sentinel('{"accuracy":0.9}'));
        }),
      }), /bundle|submission|private|changed/i);
      assert.equal(readFileSync(join(f.bundleDir, "scores.json"), "utf8"), f.publicScores);
    });
  } finally { f.cleanup(); }
});

test("private scorer discards a score if prepared evaluator data changes during scoring", async () => {
  const f = fixture();
  try {
    await f.setup();
    await withDocker(async () => {
      await assert.rejects(runPrivateScorer(f.task, f.bundle, SCORED_AT, { evaluatorRoot: f.evaluatorRoot,
        sandbox: sandbox(() => {
          writeFileSync(join(f.evaluatorRoot, "test", "labels.bin"), "changed Test bytes\n");
          return result(sentinel('{"accuracy":0.9}'));
        }),
      }), /verification|SHA-256/);
      assert.equal(readFileSync(join(f.bundleDir, "scores.json"), "utf8"), f.publicScores);
    });
  } finally { f.cleanup(); }
});

test("private scorer rejects invalid numeric output and missing primary metric", async () => {
  const f = fixture();
  try {
    await f.setup();
    await withDocker(async () => {
      const invalid = await runPrivateScorer(f.task, f.bundle, SCORED_AT, { evaluatorRoot: f.evaluatorRoot,
        sandbox: sandbox(() => result(sentinel('{"accuracy":"0.8"}'))),
      });
      assert.equal(invalid.state, "scoring_failed");
      assert.deepEqual(invalid.results, []);
      await assert.rejects(runPrivateScorer(f.task, f.bundle, SCORED_AT, { evaluatorRoot: f.evaluatorRoot,
        sandbox: sandbox(() => result(sentinel('{"loss":0.2}'))),
      }), /primary metric/);
      const nonzero = await runPrivateScorer(f.task, f.bundle, SCORED_AT, { evaluatorRoot: f.evaluatorRoot,
        sandbox: sandbox(() => result(sentinel('{"accuracy":0.8}'), 9)),
      });
      assert.equal(nonzero.state, "scoring_failed");
      assert.deepEqual(nonzero.results, []);
      assert.equal(readFileSync(join(f.bundleDir, "scores.json"), "utf8"), f.publicScores);
    });
  } finally { f.cleanup(); }
});

test("private scoring requires Docker submission isolation and a digest pinned inference image", async () => {
  const f = fixture();
  try {
    await f.setup();
    const prior = { isolation: process.env.BPB_SUBMISSION_ISOLATION, image: process.env.BPB_INFERENCE_IMAGE };
    try {
      process.env.BPB_SUBMISSION_ISOLATION = "process";
      process.env.BPB_INFERENCE_IMAGE = `fixture@sha256:${"a".repeat(64)}`;
      await assert.rejects(runPrivateScorer(f.task, f.bundle, SCORED_AT, { evaluatorRoot: f.evaluatorRoot,
        sandbox: sandbox(() => { throw new Error("must not execute"); }),
      }), /Docker isolation/);
      process.env.BPB_SUBMISSION_ISOLATION = "docker";
      process.env.BPB_INFERENCE_IMAGE = "fixture:latest";
      await assert.rejects(runPrivateScorer(f.task, f.bundle, SCORED_AT, { evaluatorRoot: f.evaluatorRoot,
        sandbox: sandbox(() => { throw new Error("must not execute"); }),
      }), /immutable inference image/);
    } finally {
      if (prior.isolation === undefined) delete process.env.BPB_SUBMISSION_ISOLATION;
      else process.env.BPB_SUBMISSION_ISOLATION = prior.isolation;
      if (prior.image === undefined) delete process.env.BPB_INFERENCE_IMAGE;
      else process.env.BPB_INFERENCE_IMAGE = prior.image;
    }
  } finally { f.cleanup(); }
});
