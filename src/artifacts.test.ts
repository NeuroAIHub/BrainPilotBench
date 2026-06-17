import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync, existsSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { filesystemArtifactSource, captureArtifacts } from "./artifacts.js";

function withTmp<T>(fn: (dir: string) => Promise<T>): Promise<T> {
  const dir = mkdtempSync(join(tmpdir(), "bpb-art-"));
  return fn(dir).finally(() => rmSync(dir, { recursive: true, force: true }));
}

test("filesystem source: 按 glob 从 <root>/<sessionId> 回收到 destDir(保留相对路径)", async () => {
  await withTmp(async (dir) => {
    const root = join(dir, "ws");
    const sid = "sess-1";
    const ws = join(root, sid);
    mkdirSync(join(ws, "sub"), { recursive: true });
    writeFileSync(join(ws, "outline.md"), "# outline");
    writeFileSync(join(ws, "sub", "fig.png"), "PNG");
    writeFileSync(join(ws, "ignore.tmp"), "x"); // 不匹配,不该回收
    const dest = join(dir, "bundle", "artifacts");
    const got = await captureArtifacts(filesystemArtifactSource(root), sid, ["*.md", "sub/*.png"], dest);
    assert.deepEqual(got.sort(), ["outline.md", "sub/fig.png"]);
    assert.equal(readFileSync(join(dest, "outline.md"), "utf8"), "# outline");
    assert.ok(existsSync(join(dest, "sub", "fig.png")));
    assert.equal(existsSync(join(dest, "ignore.tmp")), false);
  });
});

test("filesystem source: 会话 workspace 不存在 → 回收空数组(不抛)", async () => {
  await withTmp(async (dir) => {
    const got = await captureArtifacts(filesystemArtifactSource(join(dir, "ws")), "nope", ["*.md"], join(dir, "art"));
    assert.deepEqual(got, []);
  });
});

test("filesystem source: 空 globs → 空数组", async () => {
  await withTmp(async (dir) => {
    const got = await captureArtifacts(filesystemArtifactSource(join(dir, "ws")), "s", [], join(dir, "art"));
    assert.deepEqual(got, []);
  });
});
