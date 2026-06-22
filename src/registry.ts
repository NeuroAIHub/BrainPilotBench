/**
 * registry.ts — 冻结任务集发布(public face)。
 * 一个 release = 不可变命名快照:pin 到 git commit(+可选已 push 的 ref)+ task_id@version 子集
 * → BrainPilotBench-vX,论文可精确引用。slow-iterate benchmark 用命名快照,不滚动。
 *
 * 纯核心(buildRelease/addRelease/verifyRegistry 注入 git/loader 依赖,离线可测);
 * I/O(load/save)隔在边缘。git 操作(commit 解析/可达性)由 CLI 注入,本模块不 shell。
 *
 * 三个 version 别混:task `version`(单题 spec) / registry release `vX`(题集快照) / npm 包版本(框架)。
 */
import { readFileSync, existsSync, writeFileSync } from "node:fs";
import type { Task } from "./task.js";

/** 冻结进 release 的单个任务 pin。 */
export interface FrozenTask {
  id: string;
  version: string;
  category?: string;
  createdAt?: string;
}

/** 一个不可变命名发布。 */
export interface RegistryRelease {
  name: string;
  /** 冻结时的 git commit sha。 */
  commit: string;
  /** 可选:已 push 的不可变 ref(如 tag tested/...);锚定用。 */
  ref?: string;
  /** registry 自己盖的冻结日期(YYYY-MM-DD),不信任 task 自报。 */
  frozenAt: string;
  tasks: FrozenTask[];
}

export interface Registry {
  releases: RegistryRelease[];
}

/** Task[] → RegistryRelease(纯投影)。 */
export function buildRelease(name: string, commit: string, ref: string | undefined, frozenAt: string, tasks: Task[]): RegistryRelease {
  return {
    name,
    commit,
    ...(ref ? { ref } : {}),
    frozenAt,
    tasks: tasks.map((t) => ({
      id: t.meta.id,
      version: t.meta.version,
      ...(t.meta.category ? { category: t.meta.category } : {}),
      ...(t.meta.createdAt ? { createdAt: t.meta.createdAt } : {}),
    })),
  };
}

/** 公开默认 registry.json 的文件名(无 --registry 时写到这里=公开仓的提交物)。 */
export const PUBLIC_REGISTRY = "registry.json";

/**
 * 冻结误提交守卫:held-out 任务的 id/provenance 绝不能进**公开默认** registry.json
 * (内容虽扣着,但 id 列表本身就是对手想知道的"哪些题被留作终审")。
 * 判据 = 用户是否**显式**指定了 --registry:没显式指定(用默认公开路径)且含 held-out → 拦。
 * 显式给了私有路径 = 用户有意为之,放行(哪怕文件也叫 registry.json,它在私有根里)。
 * 返回错误消息;通过则返回 null。
 */
export function checkFreezeVisibility(tasks: Task[], registryExplicit: boolean): string | null {
  const heldout = tasks.filter((t) => t.meta.visibility === "heldout");
  if (!heldout.length) return null;
  if (!registryExplicit) {
    return `held-out 任务(${heldout.map((t) => t.meta.id).join(", ")})不能冻进公开默认的 ${PUBLIC_REGISTRY};` +
      `用 --registry <私有路径> 指定一个不进公开仓的 registry 文件。`;
  }
  return null;
}

/** 追加一个 release;重名 → throw(发布不可变,只能加新版本不能改旧的)。 */
export function addRelease(reg: Registry, release: RegistryRelease): Registry {
  if (reg.releases.some((r) => r.name === release.name)) {
    throw new Error(`发布名已存在,不可覆盖(发布不可变,请发新版本): ${release.name}`);
  }
  return { releases: [...reg.releases, release] };
}

/** 读 registry.json;不存在 → {releases:[]};坏 JSON → throw 清晰。 */
export function loadRegistry(path: string): Registry {
  if (!existsSync(path)) return { releases: [] };
  let raw: any;
  try { raw = JSON.parse(readFileSync(path, "utf8")); }
  catch (e) { throw new Error(`registry.json 解析失败: ${(e as Error).message}`); }
  if (raw == null || typeof raw !== "object" || !Array.isArray(raw.releases)) {
    throw new Error("registry.json 形状非法(应含 releases 数组)");
  }
  return raw as Registry;
}

/** 写 registry.json(2-space JSON + 末尾换行)。 */
export function saveRegistry(path: string, reg: Registry): void {
  writeFileSync(path, JSON.stringify(reg, null, 2) + "\n");
}

/** verifyRegistry 的注入依赖(git/loader/category,便于离线测试)。 */
export interface VerifyDeps {
  /** 当前工作树里 id → Task(loadTask 建);缺 → 任务消失。 */
  taskById: Map<string, Task>;
  /** commit sha 是否可达(git cat-file -e)。 */
  commitExists: (sha: string) => boolean;
  /** category 是否在 categories.yaml。 */
  categoryExists: (category: string) => boolean;
}

export interface ReleaseVerdict {
  release: string;
  ok: boolean;
  problems: string[];
}

/** 逐 release 校验:commit 可达、每 task 仍存在且 version 匹配、category 已知。纯函数。 */
export function verifyRegistry(reg: Registry, deps: VerifyDeps): ReleaseVerdict[] {
  const seenNames = new Set<string>();
  return reg.releases.map((rel) => {
    const problems: string[] = [];
    if (seenNames.has(rel.name)) problems.push(`release 名重复: ${rel.name}`);
    seenNames.add(rel.name);
    if (!deps.commitExists(rel.commit)) problems.push(`commit 不可达(未 push?): ${rel.commit}`);
    const tasks = Array.isArray(rel.tasks) ? rel.tasks : [];
    if (!Array.isArray(rel.tasks)) problems.push(`release ${rel.name}: tasks 非数组(registry.json 形状损坏)`);
    for (const ft of tasks) {
      if (!ft || typeof ft !== "object" || typeof (ft as { id?: unknown }).id !== "string") {
        problems.push(`release ${rel.name}: 非法 task 条目(应为含 id 的对象)`);
        continue;
      }
      const live = deps.taskById.get(ft.id);
      if (!live) { problems.push(`task missing(已删/改名): ${ft.id}`); continue; }
      if (live.meta.version !== ft.version) {
        problems.push(`task ${ft.id} version 漂移: 冻结 ${ft.version} ≠ 现 ${live.meta.version}(应发新版本)`);
      }
      if (ft.category && !deps.categoryExists(ft.category)) {
        problems.push(`task ${ft.id} 的 category 未知: ${ft.category}`);
      }
    }
    return { release: rel.name, ok: problems.length === 0, problems };
  });
}
