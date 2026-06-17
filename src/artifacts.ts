/**
 * artifacts.ts — 产物回收：把 agent 跑出的 workspace 文件按 expectedArtifacts glob
 * 收进 run bundle 的 artifacts/ 目录。可插拔 ArtifactSource(先实现文件系统同机版,
 * HTTP 版留 seam——bench 与引擎同机跑时直接读部署的 workspace 目录,不改协议)。
 */
import { glob, cp, mkdir } from "node:fs/promises";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";

/** 一个产物来源(对称于 fetcher/scorer 的可插拔模式)。 */
export interface ArtifactSource {
  /** 把 sessionId 这次会话里匹配 globs 的产物拷进 destDir;返回相对 destDir 的路径数组。 */
  collect(sessionId: string, globs: string[], destDir: string): Promise<string[]>;
}

/** 文件系统同机版:产物在 <workspaceRoot>/<sessionId>/ 下。 */
export function filesystemArtifactSource(workspaceRoot: string): ArtifactSource {
  return {
    async collect(sessionId, globs, destDir) {
      if (!globs.length) return [];
      const ws = join(workspaceRoot, sessionId);
      if (!existsSync(ws)) return [];
      const rels: string[] = [];
      for await (const rel of glob(globs, { cwd: ws })) {
        const src = join(ws, rel);
        const dst = join(destDir, rel);
        await mkdir(dirname(dst), { recursive: true });
        await cp(src, dst, { recursive: true });
        rels.push(rel);
      }
      return rels.sort();
    },
  };
}

/** CLI 调用点的稳定封装。 */
export function captureArtifacts(
  source: ArtifactSource,
  sessionId: string,
  globs: string[],
  destDir: string,
): Promise<string[]> {
  return source.collect(sessionId, globs, destDir);
}
