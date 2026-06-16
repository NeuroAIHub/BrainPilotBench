/**
 * scorer/index.ts — 公开 API + 注册内置 scorer（import 即注册，副作用一次）。
 */
export * from "./types.js";
export * from "./registry.js";

import { registerRubricScorers } from "./rubric.js";
registerRubricScorers();

export { registerRubricScorers, rubricDimensions } from "./rubric.js";
