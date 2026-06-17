/**
 * sandbox.ts — 可插拔执行沙箱(对称于 ArtifactSource/JudgeClient)。
 * 本期:本地子进程版(child_process,超时杀,工作目录限制,不注入凭证)。
 * ⚠️ 信任边界:本地子进程不是真隔离——只适合可信/自己写的 task。跨仓外部不可信
 *   task 的脚本必须等 Docker 版沙箱(留 interface seam,未来在服务器接)。
 */
import { spawn } from "node:child_process";

export interface ExecRequest {
  command: string;
  args?: string[];
  cwd: string;
  timeoutMs?: number;
}

export interface ExecResult {
  stdout: string;
  stderr: string;
  exitCode: number | null;
  timedOut: boolean;
}

export interface ExecSandbox {
  run(req: ExecRequest): Promise<ExecResult>;
}

/** 剥掉凭证的环境(防脚本读到 judge/provider key)。 */
function scrubbedEnv(): NodeJS.ProcessEnv {
  const out: NodeJS.ProcessEnv = {};
  for (const [k, v] of Object.entries(process.env)) {
    if (/API_KEY|AUTH_TOKEN|ANTHROPIC|BPB_JUDGE|OSS_|SECRET|TOKEN/i.test(k)) continue;
    out[k] = v;
  }
  return out;
}

/** 本地子进程沙箱。超时 SIGKILL;stdout/stderr 各截断 1MB 防爆内存。 */
export function localSubprocessSandbox(opts: { defaultTimeoutMs?: number } = {}): ExecSandbox {
  const defaultTimeout = opts.defaultTimeoutMs ?? 120_000;
  return {
    run(req) {
      return new Promise<ExecResult>((resolve) => {
        const timeoutMs = req.timeoutMs ?? defaultTimeout;
        // detached: 子进程自成进程组,超时时整组 SIGKILL(否则脚本里 sleep&/孙进程
        // 不被杀,会一直占着 stdout 管道,让 close 永不触发——await 挂到孙进程自然死。
        const child = spawn(req.command, req.args ?? [], {
          cwd: req.cwd,
          env: scrubbedEnv(),
          stdio: ["ignore", "pipe", "pipe"],
          detached: true,
        });
        let stdout = "";
        let stderr = "";
        let timedOut = false;
        let settled = false;
        const CAP = 1024 * 1024;
        child.stdout.on("data", (d) => { if (stdout.length < CAP) stdout += d.toString(); });
        child.stderr.on("data", (d) => { if (stderr.length < CAP) stderr += d.toString(); });

        const killGroup = () => {
          try { if (child.pid != null) process.kill(-child.pid, "SIGKILL"); } catch { /* 组已死 */ }
          try { child.kill("SIGKILL"); } catch { /* 进程已死 */ }
        };
        const done = (exitCode: number | null, extraStderr = "") => {
          if (settled) return;
          settled = true;
          clearTimeout(timer);
          // 断开管道:孤儿孙进程即便仍持有 fd,也不再让本进程的事件循环挂住。
          try { child.stdout?.destroy(); } catch { /* */ }
          try { child.stderr?.destroy(); } catch { /* */ }
          try { child.unref(); } catch { /* */ }
          resolve({ stdout, stderr: stderr + extraStderr, exitCode, timedOut });
        };
        const timer = setTimeout(() => { timedOut = true; killGroup(); }, timeoutMs);

        child.on("error", (e) => done(null, String(e)));
        // 在 exit(非 close)上结算:exit 表示直接子进程已退,即使孙进程仍占管道也不再等。
        // 给 stdout 一个微小 drain 窗口,确保已 buffer 的最后一块被收齐(小输出场景 Node
        // 通常在 exit 前已同步派发 data,这里的延迟只是保险)。
        child.on("exit", (code) => { setTimeout(() => done(code), 10); });
      });
    },
  };
}
