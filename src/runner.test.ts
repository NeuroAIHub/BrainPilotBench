/**
 * runner.test.ts — BenchRunner 关键契约的注入 fetch 测试:
 *   - onSessionReady hook 在 createSession 之后、第一条 sendMessage 之前触发
 *   - hook 抛错时 run 也抛(避免 stage 失败还去发 prompt,产生假通过)
 *   - 没给 hook 时 run 行为等同旧路径(不 break 现有 caller)
 * runtime 是 fake 的:立刻发 RUN_FINISHED 让 driveTurn 一秒内退出。
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { BenchRunner } from "./runner.js";
import type { Task } from "./task.js";

/** 只放 runner 需要看的字段;其它字段用 as 骗过 TS。 */
function makeTask(): Task {
  return {
    meta: { id: "fake", domain: "x", summary: "s", expectedArtifacts: [{ workspace: "a" }],
            timeoutMin: 1, budgetTokens: 1, requires: {}, version: "0.1" },
    turns: [{ send: "hello" }],
    askUser: {},
    rubric: { dimensions: ["x"] },
    scorers: [{ kind: "exec-script" }],
    datasets: [],
    dir: "/tmp/fake",
  } as Task;
}

/** SSE 一次性 body:一条 RUN_FINISHED 让 driveTurn 立刻 terminal。 */
function sseBody(payload: object): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  return new ReadableStream({
    start(c) { c.enqueue(enc.encode(`data: ${JSON.stringify(payload)}\n\n`)); c.close(); },
  });
}

/** 记录顺序:createSession → onSessionReady → sendMessage → stream。 */
function newTracer() {
  const order: string[] = [];
  const fetchFn: any = async (url: string, init?: RequestInit) => {
    const u = String(url);
    if (u.endsWith("/sessions") && init?.method === "POST") {
      order.push("createSession");
      return new Response(JSON.stringify({ id: "sid-42" }), { status: 200, headers: { "content-type": "application/json" } });
    }
    if (u.includes("/messages") && init?.method === "POST") {
      order.push("sendMessage");
      return new Response("", { status: 200 });
    }
    if (u.includes("/sse/") || u.includes("/events")) {
      order.push("stream");
      return new Response(sseBody({ type: "RUN_FINISHED" }) as any, { status: 200, headers: { "content-type": "text/event-stream" } });
    }
    return new Response("nope", { status: 404 });
  };
  return { order, fetchFn };
}

test("BenchRunner.run: onSessionReady 在 sendMessage 之前触发", async () => {
  const { order, fetchFn } = newTracer();
  const runner = new BenchRunner({ baseUrl: "http://x/api", fetchFn });
  const hookCalls: string[] = [];
  const res = await runner.run(makeTask(), {
    onSessionReady: async (sid) => {
      order.push("onSessionReady");
      hookCalls.push(sid);
    },
  });
  assert.equal(res.sessionId, "sid-42");
  assert.deepEqual(hookCalls, ["sid-42"]);
  // 关键顺序:create → hook → send;stream 可能与 send 交错,只断言 hook 严格夹在两者之间。
  const iCreate = order.indexOf("createSession");
  const iHook = order.indexOf("onSessionReady");
  const iSend = order.indexOf("sendMessage");
  assert.ok(iCreate >= 0 && iHook > iCreate && iSend > iHook,
    `顺序不对: ${JSON.stringify(order)}`);
});

test("BenchRunner.run: onSessionReady 抛错 → run 抛错(不悄悄跳过 setup)", async () => {
  const { fetchFn } = newTracer();
  const runner = new BenchRunner({ baseUrl: "http://x/api", fetchFn });
  await assert.rejects(
    runner.run(makeTask(), {
      onSessionReady: async () => { throw new Error("setup 失败: 缺 zstd"); },
    }),
    /setup 失败: 缺 zstd/,
  );
});

test("BenchRunner.run: 未给 hook → 行为不变(向后兼容)", async () => {
  const { order, fetchFn } = newTracer();
  const runner = new BenchRunner({ baseUrl: "http://x/api", fetchFn });
  const res = await runner.run(makeTask());
  assert.equal(res.sessionId, "sid-42");
  assert.equal(res.signals.completed, true); // RUN_FINISHED → terminal → completed
  assert.ok(!order.includes("onSessionReady"), "不该出现 hook 调用");
});
