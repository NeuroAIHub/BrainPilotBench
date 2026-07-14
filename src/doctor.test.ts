import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { runDoctor, sanitizedProxy } from "./doctor.js";
import type { Task } from "./task.js";

function makeTask(dir: string): Task {
  mkdirSync(join(dir, "env"), { recursive: true });
  writeFileSync(join(dir, "env", "requirements.txt"), "numpy>=1.24\nscikit-learn>=1.3\n");
  writeFileSync(join(dir, "env", "setup.sh"), "setup-agent.sh\n");
  writeFileSync(join(dir, "env", "setup-agent.sh"), "zstd -dc data\n");
  return {
    meta: { id: "doctor-task", domain: "d", summary: "s", expectedArtifacts: [{ workspace: "x" }], timeoutMin: 1, budgetTokens: 1, requires: {}, version: "1" },
    turns: [{ send: "x" }], askUser: {}, rubric: { dimensions: ["x"] }, scorers: [{ kind: "rubric-human" }],
    datasets: [{ name: "public.bin", scope: "public", uri: "hf://datasets/org/repo@rev/data.bin", sha256: "a".repeat(64), bytes: 100 }], dir,
  };
}

test("runDoctor reports a fully ready public task without exposing proxy credentials", async () => {
  const root = mkdtempSync(join(tmpdir(), "bpb-doctor-"));
  const proxyKeys = ["HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"];
  const previous = Object.fromEntries(proxyKeys.map((key) => [key, process.env[key]]));
  try {
    for (const key of proxyKeys) delete process.env[key];
    process.env.https_proxy = "http://secret:password@127.0.0.1:7890";
    const checks = await runDoctor({
      task: makeTask(root),
      baseUrl: "http://runtime/api",
      diskFreeBytes: 10_000,
      cacheChecker: async () => true,
      commandRunner: () => ({ ok: true, output: "1.0" }),
      fetchFn: async (input) => {
        const url = String(input);
        if (url.includes("huggingface.co")) return new Response("", { status: 200 });
        // The BrainPilot probe now requires a JSON content-type before it
        // accepts a candidate base (see detectBrainPilotBaseUrl).
        if (url === "http://runtime/health" || url === "http://runtime/sessions") {
          return new Response("{}", { status: 200, headers: { "content-type": "application/json" } });
        }
        return new Response("", { status: 404 });
      },
    });
    assert.equal(checks.some((check) => check.status === "fail"), false, JSON.stringify(checks));
    assert.equal(checks.find((check) => check.id === "brainpilot")?.status, "pass");
    assert.equal(JSON.stringify(checks).includes("password"), false);
    assert.equal(sanitizedProxy(), "http://127.0.0.1:7890");
  } finally {
    for (const key of proxyKeys) {
      if (previous[key] === undefined) delete process.env[key]; else process.env[key] = previous[key];
    }
    rmSync(root, { recursive: true, force: true });
  }
});

test("runDoctor distinguishes missing packages, disk, cache, and gated access", async () => {
  const root = mkdtempSync(join(tmpdir(), "bpb-doctor-fail-"));
  const previousToken = process.env.HF_TOKEN, previousNoFile = process.env.BPB_NO_HF_TOKEN_FILE;
  try {
    delete process.env.HF_TOKEN;
    process.env.BPB_NO_HF_TOKEN_FILE = "1";
    const task = makeTask(root);
    task.datasets[0].scope = "private";
    const checks = await runDoctor({
      task, privateData: true, diskFreeBytes: 1, cacheChecker: async () => false,
      commandRunner: (command, args) => ({ ok: command !== "python3" || !args.includes("import sklearn"), output: "ok" }),
      fetchFn: async () => new Response("", { status: 403 }),
    });
    for (const id of ["python-packages", "disk", "hf-auth", "huggingface"]) {
      assert.equal(checks.find((check) => check.id === id)?.status, "fail", `${id}: ${JSON.stringify(checks)}`);
    }
    assert.equal(checks.find((check) => check.id === "cache")?.status, "warn");
  } finally {
    if (previousToken === undefined) delete process.env.HF_TOKEN; else process.env.HF_TOKEN = previousToken;
    if (previousNoFile === undefined) delete process.env.BPB_NO_HF_TOKEN_FILE; else process.env.BPB_NO_HF_TOKEN_FILE = previousNoFile;
    rmSync(root, { recursive: true, force: true });
  }
});

test("runDoctor fails closed when requested Docker isolation is unavailable", async () => {
  const checks = await runDoctor({
    isolation: "docker",
    commandRunner: (command) => command === "docker"
      ? { ok: false, output: "daemon is not running" }
      : { ok: true, output: "1.0" },
  });
  const docker = checks.find((check) => check.id === "docker");
  assert.equal(docker?.status, "fail");
  assert.match(docker?.fix ?? "", /Docker Desktop|Docker Engine/);
});

test("runDoctor reports a missing submission inference image", async () => {
  const checks = await runDoctor({
    isolation: "docker",
    inferenceImage: "bpb-inference:test",
    commandRunner: (command, args) => {
      if (command === "docker" && args[0] === "image") return { ok: false, output: "no such image" };
      return { ok: true, output: "1.0" };
    },
  });
  assert.equal(checks.find((check) => check.id === "docker")?.status, "pass");
  assert.equal(checks.find((check) => check.id === "inference-image")?.status, "fail");
});

test("runDoctor preserves an explicitly selected Python interpreter", async () => {
  const root = mkdtempSync(join(tmpdir(), "bpb-doctor-python-"));
  const selected = join(root, ".venv", "bin", "python");
  const commands: string[] = [];
  try {
    const checks = await runDoctor({
      task: makeTask(root), pythonBinary: selected, diskFreeBytes: 10_000,
      cacheChecker: async () => true,
      commandRunner: (command, args) => {
        if (command === selected) commands.push(`${command} ${args.join(" ")}`);
        if (args[0] === "--version") return { ok: true, output: "Python 3.13.5" };
        if (args[1]?.includes("sys.executable")) return { ok: true, output: selected };
        return { ok: true, output: "ok" };
      },
      fetchFn: async () => new Response("", { status: 200 }),
    });
    assert.equal(checks.find((check) => check.id === "python")?.status, "pass");
    assert.match(checks.find((check) => check.id === "python")?.message ?? "", /\.venv\/bin\/python/);
    assert.ok(commands.some((value) => value.includes("import sklearn")));
    assert.equal(commands.every((value) => value.startsWith(selected)), true);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("runDoctor rejects unsupported Python for a numerical task", async () => {
  const root = mkdtempSync(join(tmpdir(), "bpb-doctor-version-"));
  try {
    const checks = await runDoctor({
      task: makeTask(root), diskFreeBytes: 10_000, cacheChecker: async () => true,
      commandRunner: (_command, args) => args[0] === "--version"
        ? { ok: true, output: "Python 3.9.18" }
        : { ok: true, output: "/usr/bin/python3" },
      fetchFn: async () => new Response("", { status: 200 }),
    });
    const python = checks.find((check) => check.id === "python");
    assert.equal(python?.status, "fail");
    assert.match(python?.message ?? "", /3\.10-3\.13/);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("runDoctor identifies a Python TLS certificate failure", async () => {
  const root = mkdtempSync(join(tmpdir(), "bpb-doctor-ca-"));
  try {
    const checks = await runDoctor({
      task: makeTask(root), diskFreeBytes: 10_000, cacheChecker: async () => true,
      commandRunner: (_command, args) => {
        if (args[0] === "--version") return { ok: true, output: "Python 3.13.5" };
        if (args[1]?.includes("sys.executable")) return { ok: true, output: "/tmp/.venv/bin/python" };
        if (args[1] === "import sklearn") return { ok: false, output: "ModuleNotFoundError" };
        if (args[1]?.includes("urllib.request")) {
          return { ok: false, output: "ssl.SSLCertVerificationError: CERTIFICATE_VERIFY_FAILED" };
        }
        return { ok: true, output: "ok" };
      },
      fetchFn: async () => new Response("", { status: 200 }),
    });
    const index = checks.find((check) => check.id === "python-index");
    assert.equal(index?.status, "fail");
    assert.match(index?.message ?? "", /TLS\/CA/);
    assert.match(index?.fix ?? "", /Never disable TLS/);
    assert.match(checks.find((check) => check.id === "python-packages")?.message ?? "", /\.venv\/bin\/python/);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("runDoctor verifies exact pinned Python package versions", async () => {
  const root = mkdtempSync(join(tmpdir(), "bpb-doctor-pin-"));
  try {
    const task = makeTask(root);
    writeFileSync(join(root, "env", "requirements.txt"), "numpy==2.2.6\n");
    const checks = await runDoctor({
      task, diskFreeBytes: 10_000, cacheChecker: async () => true,
      commandRunner: (_command, args) => {
        if (args[0] === "--version") return { ok: true, output: "Python 3.13.5" };
        if (args[1]?.includes("sys.executable")) return { ok: true, output: "/tmp/.venv/bin/python" };
        if (args[1]?.includes("metadata.version")) return { ok: false, output: "AssertionError" };
        return { ok: true, output: "ok" };
      },
      fetchFn: async () => new Response("", { status: 200 }),
    });
    const packages = checks.find((check) => check.id === "python-packages");
    assert.equal(packages?.status, "fail");
    assert.match(packages?.message ?? "", /numpy==2\.2\.6/);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
