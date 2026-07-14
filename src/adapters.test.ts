import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
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
    if (url === `${healthyBase}/health`) {
      return new Response("{}", { status: 200, headers: { "content-type": "application/json" } });
    }
    if (url === `${healthyBase}/sessions` && !init?.method) {
      return new Response("[]", { status: 200, headers: { "content-type": "application/json" } });
    }
    if (url.endsWith("/sessions") && init?.method === "POST") {
      return new Response(JSON.stringify({ id: "session-1" }), { status: 200, headers: { "content-type": "application/json" } });
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

/**
 * Runtime API mounted under /api, with a SPA that serves index.html on any
 * unknown route (including bare `/health` and `/sessions`). The probe must
 * refuse text/html responses so it keeps looking for the true JSON API root.
 */
function spaFrontedFetch(): typeof fetch {
  const HTML = `<!doctype html><html><body></body></html>`;
  return async (input, init) => {
    const url = String(input);
    if (url.startsWith("http://runtime/api/health")) {
      return new Response("{}", { status: 200, headers: { "content-type": "application/json" } });
    }
    if (url === "http://runtime/api/sessions" && !init?.method) {
      return new Response("[]", { status: 200, headers: { "content-type": "application/json" } });
    }
    if (url.startsWith("http://runtime/") &&
        (url.endsWith("/health") || url.endsWith("/sessions")) &&
        !init?.method) {
      return new Response(HTML, { status: 200, headers: { "content-type": "text/html; charset=utf-8" } });
    }
    return new Response("not found", { status: 404 });
  };
}

test("detectBrainPilotBaseUrl probes root and /api layouts", async () => {
  assert.equal(await detectBrainPilotBaseUrl("http://runtime/api", runtimeFetch()), "http://runtime");
  assert.equal(await detectBrainPilotBaseUrl("http://runtime", runtimeFetch("http://runtime/api")), "http://runtime/api");
  await assert.rejects(() => detectBrainPilotBaseUrl("http://missing", runtimeFetch("http://other")), /checked:/);
});

test("detectBrainPilotBaseUrl ignores SPA fallback HTML responses", async () => {
  // Deployments with a SPA at "/" serve index.html for any unknown path, so
  // GET /health and GET /sessions both return 200 text/html even though the
  // real API lives under /api. Accepting either would route POST /sessions to
  // the SPA and 404. The probe must keep looking until it finds JSON.
  assert.equal(await detectBrainPilotBaseUrl("http://runtime", spaFrontedFetch()), "http://runtime/api");
  assert.equal(await detectBrainPilotBaseUrl("http://runtime/api", spaFrontedFetch()), "http://runtime/api");
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

test("command adapter sends only the prepared workspace to its Docker executor", async () => {
  const root = mkdtempSync(join(tmpdir(), "bpb-docker-adapter-"));
  const workspaceDir = join(root, "workspace");
  try {
    const result = await new CommandAdapter({
      command: "agent",
      workspaceDir,
      isolation: { mode: "docker", image: "agent:1", user: "1000:1000" },
      dockerExecutor: async (options) => {
        assert.equal(options.image, "agent:1");
        assert.equal(options.workspaceDir, workspaceDir);
        assert.deepEqual(options.readonlyInputs, [join(workspaceDir, ".bpb")]);
        assert.equal(options.timeoutMs, 60_000);
        writeFileSync(join(workspaceDir, "result.txt"), "done");
        return { code: 0, timedOut: false };
      },
    }).run(task(root));
    assert.equal(result.status, "completed");
    assert.ok(existsSync(join(workspaceDir, "result.txt")));
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test("Docker command adapter refuses to mount a reused non-empty workspace", async () => {
  const root = mkdtempSync(join(tmpdir(), "bpb-docker-reuse-"));
  try {
    const workspaceDir = join(root, "workspace");
    await new ManualAdapter(workspaceDir).run(task(root));
    await assert.rejects(
      new CommandAdapter({
        command: "agent",
        workspaceDir,
        isolation: { mode: "docker", image: "agent:1", user: "1000:1000" },
        dockerExecutor: async () => ({ code: 0, timedOut: false }),
      }).run(task(root)),
      /new empty workspace/,
    );
  } finally { rmSync(root, { recursive: true, force: true }); }
});
