/**
 * metrics.ts — 与 scorer 正交的聚合/归一化纯函数。
 * rubric 1-5 → [0,1] 归一(可跨任务比);exec 指标(accuracy/rows_ok)是有意义数值,透传不归一。
 * pass/partial/fail → 1/0.5/0(verdict 风格)。聚合用中位数(降单 judge 方差,与 rubric judge 一致)。
 */

/** 把一个分值规整成 float:rubric 1-5 归一 [0,1];否则数值透传 / pass-partial-fail。不可解→null。 */
export function valueToFloat(v: unknown, opts: { rubric?: boolean } = {}): number | null {
  if (opts.rubric) {
    if (typeof v !== "number" || !Number.isFinite(v) || v < 1 || v > 5) return null;
    return (v - 1) / 4;
  }
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  if (v === "pass") return 1;
  if (v === "partial") return 0.5;
  if (v === "fail") return 0;
  return null;
}

/** 中位数;空数组→null;偶数取中间两数均值。 */
export function medianFloat(xs: number[]): number | null {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  const n = s.length;
  return n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2;
}
