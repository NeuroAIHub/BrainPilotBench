/**
 * @brainpilot/bench — public API.
 *
 * 注：task.js 与 validate.js 都导出名为 `validateTask` 的不同函数
 * (前者断言 Task 形状、后者跑贡献门 lint)。barrel 这里把 task.js 的同名
 * 断言重导出为 assertTaskShape 以消歧；公开的 `validateTask` = validate.js 的贡献门。
 * 两者各自的子路径 (./task / ./validate) 仍暴露原名。
 */
export {
  validateTask as assertTaskShape,
} from "./task.js";
export type {
  TaskTurn,
  ExpectedArtifact,
  TaskRequirements,
  TaskMeta,
  TaskGate,
  Rubric,
  Task,
  ScorerSpec,
} from "./task.js";
export { DEFAULT_GATE, DEFAULT_RUBRIC, DEFAULT_SCORERS } from "./task.js";
export * from "./loader.js";
export * from "./runner.js";
export * from "./scoring.js";
export * from "./scorer/index.js";
export * from "./data/index.js";
export * from "./artifacts.js";
export * from "./score.js";
export * from "./judge.js";
export * from "./sandbox.js";
export * from "./validate.js";
export * from "./categories.js";

export const BENCH_VERSION = "0.0.1";
