import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { BrainPilotAdapter, CommandAdapter, ManualAdapter, detectBrainPilotBaseUrl } from "./adapters.js";
import type { Task } from "./task.js";

function task(dir: string): Task {
  return {
    meta: { id: "adapter-task", domain: "d", summary: "s", expectedArtifacts: [{ workspace: "result.txt" }], timeoutMin: 1, budgetTokens: 1, requires: {}, version: "1" },
    turns: [{ send: "do work" }], askUser: {}, rubric: { dimensions: ["x"] },
    scorers: [{ kind: "exec-script" }], datasets: [], dir,
  };
}

function runtimeFetch(healthyBase = "http://runtime"): typeof fetch {
  return async (input, init) => {
    const url = String(input);
    if (url === `${healthyBase}/health`) return new Response("{}", { status: 200 });
    if (url === `${healthyBase}/sessions` && !init?.method) return new Response("[]", { status: 200 });
    if (url.endsWith("/sessions") && init?.method === "POST") {
      return new Response(JSON.stringify({ id: "session-1" }), { status: 200 });
    }
    if (url.includes("/messages") && init?.method === "POST") return new Response("", { status: 200 });
    if (url.includes("/sse/")) {
      const body = new ReadableStream({
        start(controller) {
          controller.enqueue(new TextEncoder().encode('data: {"type":"RUN_FINISHED"}\n\n'));
          controller.close();
        },
      });
      return new Response(body as any, { status: 200 });
    }
    return new Response("not found", { status: 404 });
  };
}

test("detectBrainPilotBaseUrl probes root and /api layouts", async () => {
  assert.equal(await detectBrainPilotBaseUrl("http://runtime/api", runtimeFetch()), "http://runtime");
  assert.equal(await detectBrainPilotBaseUrl("http://runtime", runtimeFetch("http://runtime/api")), "http://runtime/api");
  await assert.rejects(() => detectBrainPilotBaseUrl("http://missing", runtimeFetch("http://other")), /checked:/);
});

test("BrainPilotAdapter prepares the session workspace before prompting", async () => {
  const root = mkdtempSync(join(tmpdir(), "bpb-bp-adapter-"));
  try {
    const result = await new BrainPilotAdapter({ baseUrl: "http://runtime/api", workspaceRoot: root, fetchFn: runtimeFetch() }).run(task(root));
    assert.equal(result.status, "completed");
    assert.equal(result.result?.sessionId, "session-1");
    assert.ok(existsSync(join(root, "session-1", ".bpb", "TASK_PROMPT.md")));
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test("command and manual adapters share the prepared workspace contract", async () => {
  const root = mkdtempSync(join(tmpdir(), "bpb-local-adapter-"));
  const previousToken = process.env.HF_TOKEN;
  try {
    process.env.HF_TOKEN = "must-not-reach-agent";
    const commandDir = join(root, "command");
    const command = await new CommandAdapter({ command: "test -z \"$HF_TOKEN\" && printf done > result.txt", workspaceDir: commandDir }).run(task(root));
    assert.equal(command.status, "completed");
    assert.ok(existsSync(join(commandDir, "result.txt")));
    assert.ok(existsSync(join(commandDir, ".bpb", "TASK_PROMPT.md")));

    const manualDir = join(root, "manual");
    const manual = await new ManualAdapter(manualDir).run(task(root));
    assert.equal(manual.status, "pending");
    assert.ok(existsSync(join(manualDir, ".bpb", "TASK_PROMPT.md")));
  } finally {
    if (previousToken === undefined) delete process.env.HF_TOKEN; else process.env.HF_TOKEN = previousToken;
    rmSync(root, { recursive: true, force: true });
  }
});
