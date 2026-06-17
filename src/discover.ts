/**
 * discover.ts — 递归 + 多根任务发现(替换 cli 里只扫一层的 listTaskDirs)。
 * 遇到含 task.yaml 的目录即记录,不再下钻(任务内部的 checks/solution/prompt 不是任务)。
 * 跳过 node_modules 与 dot 目录。canonical = 相对根的路径无任何段以 `_` 开头
 * (示例/模板任务放 `_*` 下,默认不进 list/freeze;`includeExamples` 让 `validate all` 纳入它们)。
 */
import { readdirSync, existsSync } from "node:fs";
import { join } from "node:path";

export interface DiscoverOpts {
  /** 纳入 `_*` 前缀的示例/模板任务(validate all 用);默认 false。 */
  includeExamples?: boolean;
}

/** 在给定根集合下递归发现所有任务目录(含 task.yaml);多根去重,按路径排序。 */
export function discoverTaskDirs(roots: string[], opts: DiscoverOpts = {}): string[] {
  const includeExamples = opts.includeExamples ?? false;
  const out: string[] = [];
  const seen = new Set<string>();
  for (const root of roots) walk(root, includeExamples, out, seen);
  return out.sort();
}

function walk(dir: string, includeExamples: boolean, out: string[], seen: Set<string>): void {
  if (!existsSync(dir)) return;
  let entries;
  try { entries = readdirSync(dir, { withFileTypes: true }); } catch { return; }
  if (entries.some((e) => e.isFile() && e.name === "task.yaml")) {
    if (!seen.has(dir)) { seen.add(dir); out.push(dir); }
    return; // 任务目录是叶子:不下钻进 checks/ 等
  }
  for (const e of entries) {
    if (!e.isDirectory()) continue;
    const name = e.name;
    if (name.startsWith(".") || name === "node_modules") continue;
    if (!includeExamples && name.startsWith("_")) continue;
    walk(join(dir, name), includeExamples, out, seen);
  }
}
