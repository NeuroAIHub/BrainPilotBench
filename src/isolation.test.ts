import { test } from "node:test";
import assert from "node:assert/strict";
import { chmodSync, existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { CommandAdapter } from "./adapters.js";
import { buildDockerRunSpec, dockerImageStatus, dockerStatus } from "./isolation.js";
import type { Task } from "./task.js";

test("buildDockerRunSpec applies the fail-closed container policy", () => {
  const root = mkdtempSync(join(tmpdir(), "bpb-docker-spec-"));
  try {
    const workspace = join(root, "workspace");
    const prompt = join(workspace, ".bpb");
    const publicData = join(workspace, "public_data");
    mkdirSync(prompt, { recursive: true });
    mkdirSync(publicData);
    const spec = buildDockerRunSpec({
      image: "agent@example",
      workspaceDir: workspace,
      readonlyInputs: [prompt, publicData],
      command: "agent --prompt \"$BPB_TASK_PROMPT\"",
      taskId: "tops-fmri",
      timeoutMs: 60_000,
      user: "1000:1000",
      containerName: "bpb-test",
    });
    const rendered = spec.args.join("\n");
    assert.equal(spec.binary, "docker");
    assert.match(rendered, /--network\nnone/);
    assert.match(rendered, /--read-only/);
    assert.match(rendered, /--cap-drop\nALL/);
    assert.match(rendered, /--security-opt\nno-new-privileges/);
    assert.match(rendered, /--user\n1000:1000/);
    assert.match(rendered, /target=\/workspace\/\.bpb,readonly/);
    assert.match(rendered, /target=\/workspace\/public_data,readonly/);
    assert.doesNotMatch(rendered, /HF_TOKEN|HUGGING_FACE|PRIVATE_EVAL/);
  } finally { rmSync(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 }); }
});

test("buildDockerRunSpec rejects root, host networking, and malformed limits", () => {
  const base = {
    image: "agent:1",
    workspaceDir: "/tmp/workspace",
    readonlyInputs: [],
    command: "agent",
    taskId: "task",
    timeoutMs: 1,
  };
  assert.throws(() => buildDockerRunSpec({ ...base, user: "0:0" }), /non-root/);
  assert.throws(() => buildDockerRunSpec({ ...base, user: "1000:1000", network: "host" }), /host networking is forbidden/);
  assert.throws(() => buildDockerRunSpec({ ...base, user: "1000:1000", memory: "all" }), /--memory/);
});

test("dockerStatus is injectable for doctor checks", () => {
  assert.deepEqual(
    dockerStatus("docker", (command, args) => ({ ok: command === "docker" && args[0] === "info", output: "27.1" })),
    { ok: true, output: "27.1" },
  );
});

test("dockerImageStatus checks the exact requested image without a shell", () => {
  assert.deepEqual(
    dockerImageStatus("registry/agent@sha256:" + "a".repeat(64), "docker", (command, args) => ({
      ok: command === "docker" && args[0] === "image" && args[1] === "inspect",
      output: args.at(-1) ?? "",
    })),
    { ok: true, output: "registry/agent@sha256:" + "a".repeat(64) },
  );
});

test("Docker isolation hides host files and makes prepared inputs read-only", {
  skip: process.env.BPB_DOCKER_TEST !== "1" ? "set BPB_DOCKER_TEST=1 after pulling alpine:3.20" : false,
}, async () => {
  const root = mkdtempSync(join(tmpdir(), "bpb-docker-live-"));
  const taskDir = join(root, "task");
  const workspace = join(root, "workspace");
  const secret = join(root, "host-secret.txt");
  const previousToken = process.env.HF_TOKEN;
  try {
    process.env.HF_TOKEN = "must-not-reach-container";
    mkdirSync(join(taskDir, "env"), { recursive: true });
    const setup = join(taskDir, "env", "setup.sh");
    writeFileSync(setup, "#!/bin/bash\nset -e\nmkdir -p public_data\nprintf public > public_data/input.txt\n");
    chmodSync(setup, 0o755);
    writeFileSync(secret, "evaluator-secret");
    const task: Task = {
      meta: { id: "docker-live", domain: "d", summary: "s", expectedArtifacts: [{ workspace: "result.txt" }], timeoutMin: 1, budgetTokens: 1, requires: {}, version: "1" },
      turns: [{ send: "work" }], askUser: {}, rubric: { dimensions: ["x"] },
      scorers: [{ kind: "exec-script" }], datasets: [], dir: taskDir,
    };
    const escapedSecret = secret.replaceAll("'", "'\\''");
    const command = [
      `test ! -e '${escapedSecret}'`,
      "test -z \"$HF_TOKEN\"",
      "! touch public_data/input.txt 2>/dev/null",
      "! touch .bpb/changed 2>/dev/null",
      "printf done > result.txt",
    ].join(" && ");
    const result = await new CommandAdapter({
      command,
      workspaceDir: workspace,
      isolation: { mode: "docker", image: "alpine:3.20" },
    }).run(task);
    assert.equal(result.status, "completed");
    assert.ok(existsSync(join(workspace, "result.txt")));
  } finally {
    if (previousToken === undefined) delete process.env.HF_TOKEN; else process.env.HF_TOKEN = previousToken;
    rmSync(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 });
  }
});
