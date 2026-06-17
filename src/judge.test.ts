import { test } from "node:test";
import assert from "node:assert/strict";
import { resolveJudgeConfig, hasJudgeCreds, anthropicJudgeClient, JudgeRefusal, type JudgeConfig } from "./judge.js";

function envWith(overrides: Record<string, string | undefined>): NodeJS.ProcessEnv {
  const base: NodeJS.ProcessEnv = {};
  for (const [k, v] of Object.entries(overrides)) if (v !== undefined) base[k] = v;
  return base;
}

test("resolveJudgeConfig: BPB_JUDGE_* 覆盖 ANTHROPIC_*；默认模型 claude-opus-4-8", () => {
  const cfg = resolveJudgeConfig(envWith({ ANTHROPIC_API_KEY: "k1", ANTHROPIC_BASE_URL: "https://a" }));
  assert.equal(cfg?.key, "k1");
  assert.equal(cfg?.baseUrl, "https://a");
  assert.equal(cfg?.model, "claude-opus-4-8");
  assert.equal(cfg?.authMode, "x-api-key");
  assert.equal(cfg?.votes, 3);
  const cfg2 = resolveJudgeConfig(envWith({ ANTHROPIC_API_KEY: "k1", BPB_JUDGE_API_KEY: "k2", BPB_JUDGE_BASE_URL: "https://b", BPB_JUDGE_MODEL: "m", BPB_JUDGE_VOTES: "5" }));
  assert.equal(cfg2?.key, "k2");
  assert.equal(cfg2?.baseUrl, "https://b");
  assert.equal(cfg2?.model, "m");
  assert.equal(cfg2?.votes, 5);
});

test("resolveJudgeConfig: 只有 AUTH_TOKEN → bearer；无 key → null", () => {
  const cfg = resolveJudgeConfig(envWith({ ANTHROPIC_AUTH_TOKEN: "t1" }));
  assert.equal(cfg?.authMode, "bearer");
  assert.equal(cfg?.key, "t1");
  assert.equal(resolveJudgeConfig(envWith({})), null);
  assert.equal(hasJudgeCreds(envWith({})), false);
  assert.equal(hasJudgeCreds(envWith({ ANTHROPIC_API_KEY: "k" })), true);
});

test("resolveJudgeConfig: 默认端点 + 去尾斜杠", () => {
  const cfg = resolveJudgeConfig(envWith({ ANTHROPIC_API_KEY: "k" }));
  assert.equal(cfg?.baseUrl, "https://api.anthropic.com");
  const cfg2 = resolveJudgeConfig(envWith({ ANTHROPIC_API_KEY: "k", ANTHROPIC_BASE_URL: "https://g/" }));
  assert.equal(cfg2?.baseUrl, "https://g");
});

test("anthropicJudgeClient: x-api-key 发对 header/body,解析 text", async () => {
  const cfg: JudgeConfig = { baseUrl: "https://x", key: "k", authMode: "x-api-key", model: "claude-opus-4-8", votes: 1 };
  let seen: any = {};
  const fetchFn = (async (url: any, init: any) => {
    seen = { url, headers: init.headers, body: JSON.parse(init.body) };
    return new Response(JSON.stringify({ content: [{ type: "text", text: "GRADED" }], stop_reason: "end_turn" }), { status: 200 });
  }) as unknown as typeof fetch;
  const client = anthropicJudgeClient(cfg, { fetchFn });
  const out = await client.complete({ prompt: "p", system: "s", model: cfg.model });
  assert.equal(out, "GRADED");
  assert.equal(seen.url, "https://x/v1/messages");
  assert.equal(seen.headers["x-api-key"], "k");
  assert.equal(seen.headers["anthropic-version"], "2023-06-01");
  assert.equal(seen.body.model, "claude-opus-4-8");
  assert.equal(seen.body.system, "s");
  assert.equal(seen.body.messages[0].content, "p");
  assert.ok(seen.body.max_tokens > 0);
  assert.equal(seen.body.temperature, undefined); // opus-4-8 不接受 sampling 参数
});

test("anthropicJudgeClient: bearer 模式发 Authorization + oauth beta", async () => {
  const cfg: JudgeConfig = { baseUrl: "https://x", key: "t", authMode: "bearer", model: "m", votes: 1 };
  let headers: any = {};
  const fetchFn = (async (_u: any, init: any) => {
    headers = init.headers;
    return new Response(JSON.stringify({ content: [{ type: "text", text: "ok" }], stop_reason: "end_turn" }), { status: 200 });
  }) as unknown as typeof fetch;
  await anthropicJudgeClient(cfg, { fetchFn }).complete({ prompt: "p", model: "m" });
  assert.equal(headers["Authorization"], "Bearer t");
  assert.equal(headers["anthropic-beta"], "oauth-2025-04-20");
  assert.equal(headers["x-api-key"], undefined);
});

test("anthropicJudgeClient: refusal → 抛 JudgeRefusal", async () => {
  const cfg: JudgeConfig = { baseUrl: "https://x", key: "k", authMode: "x-api-key", model: "m", votes: 1 };
  const fetchFn = (async () =>
    new Response(JSON.stringify({ content: [], stop_reason: "refusal" }), { status: 200 })) as unknown as typeof fetch;
  await assert.rejects(() => anthropicJudgeClient(cfg, { fetchFn }).complete({ prompt: "p", model: "m" }), JudgeRefusal);
});

test("anthropicJudgeClient: 429 重试后成功", async () => {
  const cfg: JudgeConfig = { baseUrl: "https://x", key: "k", authMode: "x-api-key", model: "m", votes: 1 };
  let n = 0;
  const fetchFn = (async () => {
    n++;
    if (n === 1) return new Response("rate", { status: 429 });
    return new Response(JSON.stringify({ content: [{ type: "text", text: "ok" }], stop_reason: "end_turn" }), { status: 200 });
  }) as unknown as typeof fetch;
  const out = await anthropicJudgeClient(cfg, { fetchFn, retries: 2 }).complete({ prompt: "p", model: "m" });
  assert.equal(out, "ok");
  assert.equal(n, 2);
});

test("anthropicJudgeClient: 持续 500 → 抛(非 JudgeRefusal)", async () => {
  const cfg: JudgeConfig = { baseUrl: "https://x", key: "k", authMode: "x-api-key", model: "m", votes: 1 };
  const fetchFn = (async () => new Response("err", { status: 500 })) as unknown as typeof fetch;
  await assert.rejects(async () => {
    try { await anthropicJudgeClient(cfg, { fetchFn, retries: 1 }).complete({ prompt: "p", model: "m" }); }
    catch (e) { assert.ok(!(e instanceof JudgeRefusal)); throw e; }
  });
});
