import { test } from "node:test";
import assert from "node:assert/strict";
import { BenchRunner } from "./runner.js";
import type { Task } from "./task.js";

function makeTask(): Task {
  return {
    meta: {
      id: "fake",
      domain: "x",
      summary: "s",
      expectedArtifacts: [{ workspace: "a" }],
      timeoutMin: 1,
      budgetTokens: 1,
      requires: {},
      version: "0.1",
    },
    turns: [{ send: "hello" }],
    askUser: {},
    rubric: { dimensions: ["x"] },
    scorers: [{ kind: "exec-script" }],
    datasets: [],
    dir: "/tmp/fake",
  };
}

function sseBody(payload: object | object[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  const events = Array.isArray(payload) ? payload : [payload];
  return new ReadableStream({
    start(controller) {
      controller.enqueue(enc.encode(events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join("")));
      controller.close();
    },
  });
}

function openSseBody(payload: object[], signal?: AbortSignal | null): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      controller.enqueue(enc.encode(payload.map((event) => `data: ${JSON.stringify(event)}\n\n`).join("")));
      signal?.addEventListener("abort", () => controller.error(new Error("aborted")), { once: true });
    },
  });
}

function tracer() {
  const order: string[] = [];
  const fetchFn: typeof fetch = async (input, init) => {
    const url = String(input);
    if (url.endsWith("/sessions") && init?.method === "POST") {
      order.push("createSession");
      return new Response(JSON.stringify({ id: "sid-42" }), { status: 200 });
    }
    if (url.includes("/messages") && init?.method === "POST") {
      order.push("sendMessage");
      return new Response("", { status: 200 });
    }
    if (url.includes("/sse/") || url.includes("/events")) {
      order.push("stream");
      return new Response(sseBody({ type: "RUN_FINISHED" }) as any, { status: 200 });
    }
    return new Response("not found", { status: 404 });
  };
  return { order, fetchFn };
}

test("BenchRunner.createSession: forwards the session thinking level", async () => {
  let body: unknown;
  const fetchFn: typeof fetch = async (_input, init) => {
    body = JSON.parse(String(init?.body));
    return new Response(JSON.stringify({
      id: "sid-thinking",
      session: { thinkingLevel: "high" },
    }), { status: 200 });
  };
  const runner = new BenchRunner({ baseUrl: "http://runtime", fetchFn, thinkingLevel: "high" });
  assert.equal(await runner.createSession(), "sid-thinking");
  assert.deepEqual(body, { thinkingLevel: "high" });
});

test("BenchRunner.createSession: forwards BPB_THINKING_LEVEL used by the adapter", async (t) => {
  const previous = process.env.BPB_THINKING_LEVEL;
  t.after(() => {
    if (previous === undefined) delete process.env.BPB_THINKING_LEVEL;
    else process.env.BPB_THINKING_LEVEL = previous;
  });
  process.env.BPB_THINKING_LEVEL = "high";

  let body: unknown;
  const fetchFn: typeof fetch = async (_input, init) => {
    body = JSON.parse(String(init?.body));
    return new Response(JSON.stringify({
      id: "sid-thinking-env",
      session: { thinkingLevel: "high" },
    }), { status: 201 });
  };
  const runner = new BenchRunner({ baseUrl: "http://runtime", fetchFn });
  assert.equal(await runner.createSession(), "sid-thinking-env");
  assert.deepEqual(body, { thinkingLevel: "high" });
});

test("BenchRunner.createSession: rejects a silently downgraded thinking level", async () => {
  const fetchFn: typeof fetch = async () => new Response(JSON.stringify({
    id: "sid-thinking",
    session: { thinkingLevel: "medium" },
  }), { status: 200 });
  const runner = new BenchRunner({ baseUrl: "http://runtime", fetchFn, thinkingLevel: "high" });
  await assert.rejects(
    runner.createSession(),
    /thinking level mismatch: requested high, observed medium/,
  );
});

test("BenchRunner.run: setup hook runs before the first prompt", async () => {
  const { order, fetchFn } = tracer();
  const result = await new BenchRunner({ baseUrl: "http://runtime", fetchFn }).run(makeTask(), {
    onSessionReady: async (sessionId) => {
      assert.equal(sessionId, "sid-42");
      order.push("setup");
    },
  });
  assert.equal(result.sessionId, "sid-42");
  assert.ok(order.indexOf("createSession") < order.indexOf("setup"));
  assert.ok(order.indexOf("setup") < order.indexOf("sendMessage"));
});

test("BenchRunner.run: wait_idle consumes overlapping child runs before completing", async () => {
  const events = [
    { type: "RUN_STARTED", run_id: "principal" },
    { type: "RUN_STARTED", run_id: "engineer" },
    { type: "RUN_FINISHED", run_id: "principal" },
    { type: "TOOL_CALL_START", run_id: "engineer" },
    { type: "RUN_FINISHED", run_id: "engineer" },
  ];
  const fetchFn: typeof fetch = async (input, init) => {
    const url = String(input);
    if (url.endsWith("/sessions") && init?.method === "POST") {
      return new Response(JSON.stringify({ id: "sid-multi" }), { status: 200 });
    }
    if (url.includes("/messages") && init?.method === "POST") return new Response("", { status: 200 });
    if (url.includes("/sse/") || url.includes("/events")) {
      return new Response(openSseBody(events, init?.signal) as any, { status: 200 });
    }
    return new Response("not found", { status: 404 });
  };
  const task = makeTask();
  task.turns[0].then = "wait_idle";
  const result = await new BenchRunner({ baseUrl: "http://runtime", fetchFn, settleMs: 10 }).run(task);
  assert.equal(result.reason, "completed");
  assert.equal(result.signals.eventCount, events.length);
  assert.equal(result.signals.toolCalls, 1);
});

test("BenchRunner.run: setup failure stops the run before prompting", async () => {
  const { order, fetchFn } = tracer();
  await assert.rejects(
    new BenchRunner({ baseUrl: "http://runtime", fetchFn }).run(makeTask(), {
      onSessionReady: async () => { throw new Error("public setup failed"); },
    }),
    /public setup failed/,
  );
  assert.equal(order.includes("sendMessage"), false);
});

test("BenchRunner.run: omitting the setup hook remains supported", async () => {
  const { order, fetchFn } = tracer();
  const result = await new BenchRunner({ baseUrl: "http://runtime", fetchFn }).run(makeTask());
  assert.equal(result.sessionId, "sid-42");
  assert.equal(result.signals.completed, true);
  assert.equal(order.includes("setup"), false);
});
