/**
 * scorer/registry.ts — kind → ScorerModule 的开放命名注册表
 * (对照 lm-eval @register_metric / HELM MetricSpec；拒绝 BIG-bench 封闭枚举)。
 */
import type { ScorerModule } from "./types.js";

const REGISTRY = new Map<string, ScorerModule>();

export function registerScorer(kind: string, mod: ScorerModule): void {
  REGISTRY.set(kind, mod);
}

export function getScorerModule(kind: string): ScorerModule {
  const m = REGISTRY.get(kind);
  if (!m) throw new Error(`unknown scorer kind: ${kind} (registered: ${[...REGISTRY.keys()].join(", ") || "none"})`);
  return m;
}

export function hasScorer(kind: string): boolean {
  return REGISTRY.has(kind);
}

export function listScorers(): string[] {
  return [...REGISTRY.keys()];
}
