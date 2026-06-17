import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync, chmodSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { localSubprocessSandbox } from "./sandbox.js";

function withTmp<T>(fn: (dir: string) => Promise<T>): Promise<T> {
  const dir = mkdtempSync(join(tmpdir(), "bpb-sbx-"));
  return fn(dir).finally(() => rmSync(dir, { recursive: true, force: true }));
}

test("localSubprocessSandbox: 跑脚本拿 stdout + exit 0", async () => {
  await withTmp(async (dir) => {
    const sh = join(dir, "ok.sh");
    writeFileSync(sh, "#!/bin/bash\necho hello-exec\nexit 0\n");
    chmodSync(sh, 0o755);
    const r = await localSubprocessSandbox().run({ command: "/bin/bash", args: [sh], cwd: dir });
    assert.equal(r.exitCode, 0);
    assert.ok(r.stdout.includes("hello-exec"));
    assert.equal(r.timedOut, false);
  });
});

test("localSubprocessSandbox: 非0退出码如实返回", async () => {
  await withTmp(async (dir) => {
    const sh = join(dir, "fail.sh");
    writeFileSync(sh, "#!/bin/bash\necho oops >&2\nexit 3\n");
    chmodSync(sh, 0o755);
    const r = await localSubprocessSandbox().run({ command: "/bin/bash", args: [sh], cwd: dir });
    assert.equal(r.exitCode, 3);
    assert.ok(r.stderr.includes("oops"));
  });
});

test("localSubprocessSandbox: 超时 → SIGKILL + timedOut + 快速返回(不等孙进程)", async () => {
  await withTmp(async (dir) => {
    const sh = join(dir, "hang.sh");
    writeFileSync(sh, "#!/bin/bash\nsleep 30\n");
    chmodSync(sh, 0o755);
    const t0 = Date.now();
    const r = await localSubprocessSandbox().run({ command: "/bin/bash", args: [sh], cwd: dir, timeoutMs: 300 });
    const elapsed = Date.now() - t0;
    assert.equal(r.timedOut, true);
    assert.notEqual(r.exitCode, 0);
    assert.ok(elapsed < 5000, `run() should return shortly after timeout, took ${elapsed}ms`);
  });
});

test("localSubprocessSandbox: 后台孙进程不阻塞返回(成功 grader 里 sleep&)", async () => {
  await withTmp(async (dir) => {
    const sh = join(dir, "bg.sh");
    // 脚本背景化一个长 sleep 后立刻 exit 0:旧实现会在 close 上挂到孙进程死。
    writeFileSync(sh, "#!/bin/bash\nsleep 30 &\necho done\nexit 0\n");
    chmodSync(sh, 0o755);
    const t0 = Date.now();
    const r = await localSubprocessSandbox().run({ command: "/bin/bash", args: [sh], cwd: dir, timeoutMs: 10000 });
    const elapsed = Date.now() - t0;
    assert.equal(r.exitCode, 0);
    assert.ok(r.stdout.includes("done"));
    assert.equal(r.timedOut, false);
    assert.ok(elapsed < 5000, `run() should return on child exit, not wait for backgrounded grandchild; took ${elapsed}ms`);
  });
});

test("localSubprocessSandbox: cwd 生效", async () => {
  await withTmp(async (dir) => {
    const sh = join(dir, "pwd.sh");
    writeFileSync(sh, "#!/bin/bash\npwd\n");
    chmodSync(sh, 0o755);
    const r = await localSubprocessSandbox().run({ command: "/bin/bash", args: [sh], cwd: dir });
    // macOS /var → /private/var symlink;用 endsWith 容差
    assert.ok(r.stdout.trim().endsWith(dir.replace(/^\/private/, "")) || r.stdout.includes(dir.split("/").pop()!));
  });
});

test("localSubprocessSandbox: 不向子进程注入凭证 env", async () => {
  await withTmp(async (dir) => {
    const prev = process.env.ANTHROPIC_API_KEY;
    process.env.ANTHROPIC_API_KEY = "sk-should-not-leak";
    const sh = join(dir, "env.sh");
    writeFileSync(sh, '#!/bin/bash\necho "KEY=[${ANTHROPIC_API_KEY}]"\n');
    chmodSync(sh, 0o755);
    try {
      const r = await localSubprocessSandbox().run({ command: "/bin/bash", args: [sh], cwd: dir });
      assert.ok(r.stdout.includes("KEY=[]"), `expected stripped key, got: ${r.stdout}`);
    } finally {
      if (prev === undefined) delete process.env.ANTHROPIC_API_KEY; else process.env.ANTHROPIC_API_KEY = prev;
    }
  });
});
