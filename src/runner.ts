/**
 * runner.ts — Run a Task against a live BrainPilot deployment.
 *
 * Thin connection layer over the Runtime HTTP contract: routes come from
 * `@brainpilot/protocol` RUNTIME_ROUTES (SSOT — no hardcoded paths), only the
 * fetch/SSE glue lives here. (We deliberately do NOT publish a shared client
 * package; the contract that matters is pinned via protocol, the ~100 lines of
 * glue are cheap to keep local — same call made for the cloud testbed harness.)
 *
 * A run: create session → inject turns (auto-answer ask_user) → collect events
 * → record auto-signals (completed / events / errors / produced files) →
 * return a result the demo-bundle builder + scoring scaffold consume.
 */
import { RUNTIME_ROUTES } from "@brainpilot/protocol";
import { type Task, type TaskTurn } from "./task.js";
import { answerFor } from "./loader.js";

function fillPath(tmpl: string, params: Record<string, string> = {}): string {
  return tmpl.replace(/:([A-Za-z0-9_]+)/g, (_, n) => {
    if (params[n] === undefined) throw new Error(`missing path param :${n}`);
    return encodeURIComponent(params[n]);
  });
}

export interface RunnerOptions {
  /** Deployment base URL, e.g. http://127.0.0.1:9001 */
  baseUrl: string;
  /** Per-event no-activity timeout (ms). Falls back to task.timeoutMin otherwise. */
  idleMs?: number;
  /** Quiet period after all observed runs finish before declaring session idle. */
  settleMs?: number;
  fetchFn?: typeof fetch;
  /** Session-wide reasoning effort shared by every BrainPilot agent. */
  thinkingLevel?: "off" | "low" | "medium" | "high";
}

export interface RunResult {
  taskId: string;
  sessionId: string;
  /** Full ordered AG-UI events (the bundle's timeline source). */
  events: any[];
  /** Why the run ended. */
  reason: "completed" | "timeout" | "stream_end" | "error";
  /** Auto-signals (NOT a quality verdict — those come from rubric scoring). */
  signals: {
    completed: boolean;
    eventCount: number;
    textContentEvents: number;
    toolCalls: number;
    errorEvents: number;       // RUN_ERROR + system_message(level error/fatal)
    durationMs: number;
  };
}

const isTerminal = (e: any) => e?.type === "RUN_FINISHED" || e?.type === "RUN_ERROR";
type TurnResult = "completed" | "timeout" | "stream_end" | "error";

/** Minimal SSE frame parser (multi-line data:, cross-chunk). */
async function* parseSse(body: ReadableStream<Uint8Array>): AsyncGenerator<any> {
  const dec = new TextDecoder();
  const reader = body.getReader();
  let buf = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (value) buf += dec.decode(value, { stream: true });
      let i: number;
      while ((i = boundary(buf)) !== -1) {
        const frame = buf.slice(0, i);
        buf = buf.slice(i).replace(/^(\r?\n){1,2}/, "");
        const evt = decodeFrame(frame);
        if (evt) yield evt;
      }
      if (done) break;
    }
    const evt = decodeFrame(buf);
    if (evt) yield evt;
  } finally {
    reader.releaseLock();
  }
}
function boundary(b: string): number {
  const a = b.indexOf("\n\n"), c = b.indexOf("\r\n\r\n");
  return a === -1 ? c : c === -1 ? a : Math.min(a, c);
}
function decodeFrame(frame: string): any {
  const lines = frame.split(/\r?\n/).filter((l) => l.startsWith("data:")).map((l) => l.slice(5).replace(/^ /, ""));
  if (!lines.length) return null;
  const p = lines.join("\n").trim();
  if (!p || p === "[DONE]") return null;
  try { return JSON.parse(p); } catch { return null; }
}

export class BenchRunner {
  private base: string;
  private fetchFn: typeof fetch;
  private configuredIdleMs?: number;
  private configuredSettleMs?: number;
  private thinkingLevel?: "off" | "low" | "medium" | "high";
  constructor(opts: RunnerOptions) {
    this.base = opts.baseUrl.replace(/\/+$/, "");
    this.fetchFn = opts.fetchFn ?? fetch;
    this.configuredIdleMs = opts.idleMs;
    this.configuredSettleMs = opts.settleMs;
    const thinkingLevel = opts.thinkingLevel ?? process.env.BPB_THINKING_LEVEL;
    if (thinkingLevel && !["off", "low", "medium", "high"].includes(thinkingLevel)) {
      throw new Error(`invalid BPB_THINKING_LEVEL: ${thinkingLevel}`);
    }
    this.thinkingLevel = thinkingLevel as RunnerOptions["thinkingLevel"];
  }
  private url(tmpl: string, params?: Record<string, string>) { return this.base + fillPath(tmpl, params); }

  async createSession(): Promise<string> {
    const r = await this.fetchFn(this.url(RUNTIME_ROUTES.createSession.path), {
      method: RUNTIME_ROUTES.createSession.method,
      headers: { "content-type": "application/json" },
      body: JSON.stringify(this.thinkingLevel ? { thinkingLevel: this.thinkingLevel } : {}),
    });
    if (!r.ok) throw new Error(`createSession ${r.status}`);
    const created = await r.json() as {
      id: string;
      session?: { thinkingLevel?: string };
    };
    if (this.thinkingLevel) {
      const observed = created.session?.thinkingLevel;
      if (observed !== this.thinkingLevel) {
        throw new Error(
          `createSession thinking level mismatch: requested ${this.thinkingLevel}, observed ${observed ?? "missing"}`,
        );
      }
    }
    return created.id;
  }
  private async send(sid: string, content: string): Promise<void> {
    const r = await this.fetchFn(this.url(RUNTIME_ROUTES.sendMessage.path, { id: sid }), {
      method: RUNTIME_ROUTES.sendMessage.method,
      headers: { "content-type": "application/json" }, body: JSON.stringify({ content }),
    });
    if (!r.ok) throw new Error(`sendMessage ${r.status}`);
  }
  private async *stream(sid: string, signal: AbortSignal): AsyncGenerator<any> {
    const r = await this.fetchFn(this.url(RUNTIME_ROUTES.sessionEvents.path, { id: sid }),
      { headers: { accept: "text/event-stream" }, signal });
    if (!r.ok || !r.body) throw new Error(`stream ${r.status}`);
    yield* parseSse(r.body as ReadableStream<Uint8Array>);
  }

  /** Drive one turn until its declared completion policy is satisfied. */
  private async driveTurn(
    sid: string,
    turn: TaskTurn,
    task: Task,
    idleMs: number,
    settleMs: number,
    deadline: number,
    acc: any[],
  ): Promise<TurnResult> {
    const ctrl = new AbortController();
    const stream = this.stream(sid, ctrl.signal);
    await this.send(sid, turn.send);
    if (turn.then === "none") return "completed";

    let last = Date.now();
    let timedOut = false;
    let settled = false;
    let sawTerminal = false;
    let lastTerminalWasError = false;
    const activeRuns = new Set<string>();
    const timer = setInterval(() => {
      const now = Date.now();
      if (now >= deadline || now - last > idleMs) {
        timedOut = true;
        ctrl.abort();
      } else if ((turn.then ?? "wait_idle") === "wait_idle" && sawTerminal && activeRuns.size === 0 && now - last >= settleMs) {
        settled = true;
        ctrl.abort();
      }
    }, Math.max(10, Math.min(250, settleMs)));
    let streamEnded = false;
    try {
      for await (const e of stream) {
        acc.push(e); last = Date.now();
        const runId = typeof e?.run_id === "string" ? e.run_id : undefined;
        if ((e?.type === "RUN_STARTED" || (e?.type === "agent_status_update" && e?.status === "running")) && runId) {
          activeRuns.add(runId);
        }
        if (isTerminal(e)) {
          sawTerminal = true;
          lastTerminalWasError = e.type === "RUN_ERROR";
          if (runId) activeRuns.delete(runId);
        }
        if (e?.type === "agent_status_update" && e?.status === "idle" && runId) activeRuns.delete(runId);
        // auto-answer ask_user
        if (e.type === "user_input_request") {
          const ans = answerFor(task.askUser, e.question ?? "");
          if (ans !== undefined) {
            await this.fetchFn(this.url(RUNTIME_ROUTES.sendMessage.path, { id: sid }), {
              method: "POST", headers: { "content-type": "application/json" },
              body: JSON.stringify({ content: ans }),
            }).catch(() => {});
          }
        }
        if ((turn.then === "interrupt") && isTerminal(e)) {
          return lastTerminalWasError ? "error" : "completed";
        }
      }
      streamEnded = true;
    } catch {
      if (!ctrl.signal.aborted) return "error";
    }
    finally { clearInterval(timer); ctrl.abort(); }
    if (timedOut) return "timeout";
    if (settled || (streamEnded && sawTerminal && activeRuns.size === 0)) {
      return lastTerminalWasError ? "error" : "completed";
    }
    return "stream_end";
  }

  /**
   * Run a full task. onSessionReady is the lifecycle boundary for staging
   * public data after a session id exists but before the first agent prompt.
   */
  async run(task: Task, opts?: {
    idleMs?: number;
    settleMs?: number;
    onSessionReady?: (sessionId: string) => Promise<void>;
  }): Promise<RunResult> {
    const started = Date.now();
    const taskTimeoutMs = task.meta.timeoutMin * 60_000;
    const deadline = started + taskTimeoutMs;
    const idleMs = opts?.idleMs ?? this.configuredIdleMs ?? taskTimeoutMs;
    const settleMs = opts?.settleMs ?? this.configuredSettleMs ?? 500;
    const sid = await this.createSession();
    if (opts?.onSessionReady) await opts.onSessionReady(sid);
    const events: any[] = [];
    let reason: RunResult["reason"] = "completed";
    for (const turn of task.turns) {
      const result = await this.driveTurn(sid, turn, task, idleMs, settleMs, deadline, events);
      if (result !== "completed") { reason = result; break; }
    }
    const count = (t: string) => events.filter((e) => e?.type === t).length;
    const errorEvents = count("RUN_ERROR") +
      events.filter((e) => e?.type === "system_message" && (e.level === "error" || e.level === "fatal")).length;
    return {
      taskId: task.meta.id,
      sessionId: sid,
      events,
      reason,
      signals: {
        completed: reason === "completed",
        eventCount: events.length,
        textContentEvents: count("TEXT_MESSAGE_CONTENT") + count("TEXT_MESSAGE_CHUNK"),
        toolCalls: count("TOOL_CALL_START"),
        errorEvents,
        durationMs: Date.now() - started,
      },
    };
  }
}
