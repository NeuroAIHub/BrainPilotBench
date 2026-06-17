/**
 * judge.ts — LLM judge 客户端:手写 fetch 打 Anthropic Messages API(零依赖)。
 * 配置全走环境变量,仓库永不出现 endpoint/key。BPB_JUDGE_* 覆盖 ANTHROPIC_*。
 * 任意 Anthropic-Messages 兼容端点都能插(官方/网关/反代),BYO provider。
 */
export interface JudgeRequest {
  system?: string;
  prompt: string;
  model: string;
  maxTokens?: number;
}

export interface JudgeClient {
  complete(req: JudgeRequest): Promise<string>;
}

/** judge 拒答(safety refusal / 空内容):不计分,交上层作 unscored。 */
export class JudgeRefusal extends Error {}

export interface JudgeConfig {
  baseUrl: string;
  key: string;
  authMode: "x-api-key" | "bearer";
  model: string;
  votes: number;
}

const DEFAULT_MODEL = "claude-opus-4-8";
const DEFAULT_BASE = "https://api.anthropic.com";

/** 从环境解析 judge 配置;无 key 返回 null。BPB_JUDGE_* 优先于 ANTHROPIC_*。 */
export function resolveJudgeConfig(env: NodeJS.ProcessEnv = process.env): JudgeConfig | null {
  const apiKey = env.BPB_JUDGE_API_KEY || env.ANTHROPIC_API_KEY;
  const authToken = env.ANTHROPIC_AUTH_TOKEN;
  const key = apiKey || authToken;
  if (!key) return null;
  const baseUrl = (env.BPB_JUDGE_BASE_URL || env.ANTHROPIC_BASE_URL || DEFAULT_BASE).replace(/\/+$/, "");
  const model = env.BPB_JUDGE_MODEL || DEFAULT_MODEL;
  const votes = Number.parseInt(env.BPB_JUDGE_VOTES || "3", 10);
  return {
    baseUrl,
    key,
    authMode: apiKey ? "x-api-key" : "bearer",
    model,
    votes: Number.isFinite(votes) && votes > 0 ? votes : 3,
  };
}

export function hasJudgeCreds(env: NodeJS.ProcessEnv = process.env): boolean {
  return resolveJudgeConfig(env) !== null;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** 手写 Anthropic Messages 客户端。opts.fetchFn 便于离线测试;retries 退避 429/5xx。 */
export function anthropicJudgeClient(cfg: JudgeConfig, opts: { fetchFn?: typeof fetch; retries?: number } = {}): JudgeClient {
  const doFetch = opts.fetchFn ?? fetch;
  const retries = opts.retries ?? 3;
  return {
    async complete(req) {
      const headers: Record<string, string> = {
        "content-type": "application/json",
        "anthropic-version": "2023-06-01",
      };
      if (cfg.authMode === "bearer") {
        headers["Authorization"] = `Bearer ${cfg.key}`;
        headers["anthropic-beta"] = "oauth-2025-04-20";
      } else {
        headers["x-api-key"] = cfg.key;
      }
      // 注意:opus-4-8 不接受 temperature/top_p/top_k(会 400);不传 thinking(省 token)。
      const body = JSON.stringify({
        model: req.model,
        max_tokens: req.maxTokens ?? 1024,
        ...(req.system ? { system: req.system } : {}),
        messages: [{ role: "user", content: req.prompt }],
      });
      let lastErr: unknown;
      for (let attempt = 0; attempt <= retries; attempt++) {
        let res: Response;
        try {
          res = await doFetch(`${cfg.baseUrl}/v1/messages`, { method: "POST", headers, body });
        } catch (e) {
          lastErr = e;
          if (attempt < retries) { await sleep(250 * 2 ** attempt); continue; }
          throw e;
        }
        if (res.status === 429 || res.status >= 500) {
          lastErr = new Error(`judge HTTP ${res.status}`);
          if (attempt < retries) { await sleep(250 * 2 ** attempt); continue; }
          throw lastErr;
        }
        if (!res.ok) throw new Error(`judge HTTP ${res.status}`);
        const data: any = await res.json();
        if (data?.stop_reason === "refusal") throw new JudgeRefusal("judge refused");
        const text = Array.isArray(data?.content)
          ? data.content.filter((b: any) => b?.type === "text").map((b: any) => b.text).join("")
          : "";
        if (!text) throw new JudgeRefusal("judge returned empty content");
        return text;
      }
      throw lastErr ?? new Error("judge failed");
    },
  };
}
