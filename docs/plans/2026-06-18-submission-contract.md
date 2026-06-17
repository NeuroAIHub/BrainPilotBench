# Submission/bundle contract — Implementation Plan

> REQUIRED SUB-SKILL: subagent-driven-development (implementer→spec审→质量审 per task),最后 opus 全量 review。

**Goal:** 把「submission bundle」做成系统无关的评测输入正式接口——任何 agent(任何语言/harness)产出符合格式的 bundle → `bp-bench submit verify` 校验 → `bp-bench score` 评分 → `leaderboard`。**本轮不做 live-driving / SUTAdapter**(用户已选先做提交契约,驱动留下一步)。这是让外部 agent 今天就能被评的「交付物件」。

**Bundle 契约:**
```
<bundle>/
  meta.json                    # 提交清单
  artifacts/<files>            # 必须满足任务 expected_artifacts 的 glob
  events.jsonl                 # 可选轨迹(为将来 trajectory 评分预留)
```
`meta.json`:
```json
{ "taskId": "<id>",            // 必填:哪个任务
  "agent": "name@version",     // 必填:被评系统标识 → leaderboard 行身份(task@agent)
  "taskVersion": "0.1",        // 可选:针对的任务 spec 版本(记录/可比)
  "producedAt": "2026-06-18",  // 可选 ISO
  "notes": "..." }             // 可选
```

**关键语义:**
- `score` 跑的是**任务声明的 scorer**(exec 确定性 / rubric+judge),提交者不选 scorer → 防作弊不变。
- `meta.agent` 映射到 `RunScores.version`,leaderboard 行 = `task@agent`(不同 agent/版本是不同行)。
- `score` **同时接受** `meta.json`(提交)与 `signals.json`(内部 `run`,不动)。

**Tech:** TS NodeNext strict → tsc → dist;node:test;**零新依赖**;Node≥22。提交信息结尾:`Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`。base `main`,现有 **121 单测**全绿(含 Phase 1 golden 逐字节)。

## 文件结构

| 文件 | 职责 |
|---|---|
| `src/submission.ts` | 创建。`SubmissionMeta`/`loadSubmissionMeta`/`verifySubmission` |
| `src/submission.test.ts` | 创建。verify 各分支 + load |
| `src/cli.ts` | 修改。`submit verify` 分支 + `score` 接受 meta.json + usage |
| `src/index.ts` | 修改。`export * from "./submission.js"` |
| `package.json` | 修改。exports 加 `./submission` |
| `README.md` | 修改。"Evaluating your own agent" 一节 + bundle 格式 |
| `examples/submission/` | 创建。示例 bundle 模板(meta.json + artifacts/ + README) |

> 复用不改:`loadTask`/`runScorers`/`RunBundle`/`bundleWorkspaceFiles`。`run` 内部产出 signals.json 路径不动。

---

## Task 1: src/submission.ts(提交契约纯核心)

**Interfaces:**
- `interface SubmissionMeta { taskId: string; agent: string; taskVersion?: string; producedAt?: string; notes?: string }`
- `interface SubmissionIssue { level: "error" | "warn"; msg: string }`(本地轻量,避免 import validate.ts 的 sandbox/scorer 重依赖)
- `loadSubmissionMeta(dir: string): SubmissionMeta | null`(读 `<dir>/meta.json`;不存在→null;坏 JSON→throw 清晰)
- `verifySubmission(task: Task, dir: string): SubmissionIssue[]`:
  - meta.json 存在且 `taskId`/`agent` 为非空 string;`meta.taskId === task.meta.id`(不一致→error)
  - 每个 `task.meta.expectedArtifacts[].workspace` glob 在 `<dir>/artifacts/` 下至少匹配 1 个文件(否则 error `缺产物: <glob>`)
  - artifacts 下文件名/meta 字段无 `..` 穿越
  - `events.jsonl` 若存在:逐行 `JSON.parse`,坏行→warn(可选轨迹,不阻断)

- [ ] Step1 写 `src/submission.test.ts`(tmpdir 造 bundle):①好 bundle(meta + artifacts 满足 glob)→ 无 error;②缺 meta.json → error;③meta.taskId≠task.id → error;④缺某 expected_artifact → error 含该 glob;⑤坏 events.jsonl 行 → warn 非 error;⑥`loadSubmissionMeta` 解析 + 不存在→null。用 `globSync`(node:fs)匹配,与 `bundleWorkspaceFiles` 一致。
- [ ] Step2 build RED(`./submission.js` 不存在)。
- [ ] Step3 写 `src/submission.ts`。
- [ ] Step4 build+test GREEN(总 121 + 新增,`# fail 0`)。
- [ ] Step5 提交:`feat(submission): 提交 bundle 契约核心(meta + verifySubmission 校验 expected_artifacts)`

---

## Task 2: CLI `submit verify` + `score` 接受 meta.json

**Files:** Modify `src/cli.ts`、`src/index.ts`、`package.json`。

- [ ] Step1 `cli.ts` import `loadSubmissionMeta`/`verifySubmission`。
- [ ] Step2 新增分支 `cmd === "submit" && argv[1] === "verify"`:`const dir = argv[2]`;`loadSubmissionMeta(dir)` 拿 taskId → `dirsByTaskId(taskId)[0]` → loadTask;跑 `verifySubmission(task, dir)`;打印 ✓/✗ + 各 issue;有 error → exit 1。无 meta/找不到 task → 清晰报错 exit 2。
- [ ] Step3 改 `score` 分支:优先读 `<dir>/meta.json`(submission),否则回落 `signals.json`(内部 run)。meta 路径:`taskId=meta.taskId`,`version=meta.agent`,`runId=meta.runId ?? ${taskId}-${meta.agent}`(sanitize 空格→`-`),`signals=meta`。signals 路径保持现状。其余(events 读取、runScorers、写 scores.json、打印)不变。
- [ ] Step4 `index.ts` 加 `export * from "./submission.js"`;`package.json` exports 加 `"./submission": "./dist/submission.js"`;usage 串加 `submit verify <bundle>`。
- [ ] Step5 typecheck+build+test 全绿;**e2e**:造一个 meta.json bundle(exec demo 任务,artifacts/results.csv),`submit verify` → ✓;删产物 → ✗ exit1;`score` 该 bundle → scores.json 真分;`leaderboard` → 行 = `task@agent`。
- [ ] Step6 提交:`feat(cli): submit verify 校验提交 bundle + score 接受 meta.json(leaderboard 行=task@agent)`

---

## Task 3: 文档 + 示例 bundle

**Files:** Create `examples/submission/`(meta.json + artifacts/ + 一行 README);Modify `README.md`。

- [ ] Step1 `examples/submission/`:一个针对某任务的最小示例 bundle(meta.json 填 taskId/agent + artifacts/ 放一个占位产物 + 说明这是模板)。
- [ ] Step2 README 加 **"Evaluating your own agent"** 一节:bundle 布局 + 流程(读 `tasks/<id>/` 的 summary/turns/expected_artifacts → 用你的 agent 跑 `prompt/turns.yaml` 产出产物 → 摆成 bundle → `bp-bench submit verify` → `bp-bench score` → `bp-bench leaderboard`)。明确标注:`run`/live-driving(任意 agent 一键驱动)是 deferred 的 SUT-adapter 后续。
- [ ] Step3 验证 `list`/`validate all` 不受影响;`submit verify examples/submission`(若示例指向真任务)给出明确结果。提交:`docs(submission): README "Evaluating your own agent" + 示例 bundle 模板`

---

## 验收标准

- typecheck+build+test 全绿(121 + ~6 submission),零新依赖,Phase 1 golden 逐字节不变。
- `submit verify` 抓缺产物 / meta.taskId 不符 / 坏 meta;`score` 从 meta.json bundle 端到端出真分(exec),leaderboard 行 = `task@agent`。
- 内部 `bp-bench run`(signals.json)路径不变。
- README "Evaluating your own agent" + `examples/submission/` 落地;明确标注 live-driving 是后续 SUT-adapter。
- 最后 opus 全量对抗 review 再 merge。

## 自检(writing-plans self-review)

- **范围**:只做提交契约(用户拍板),不碰 runner.ts / 不建 SUTAdapter。`score` 双读 meta/signals 是加法式向后兼容。
- **类型一致**:`SubmissionMeta`/`verifySubmission` 跨 Task 一致;复用 `Task`/`loadTask`/`runScorers`/`globSync`(与 `bundleWorkspaceFiles` 同源)。
- **承重墙**:`score` 仍跑任务声明的 scorer(提交者不选 scorer)→ 防作弊不变;rubric 真分仍需 judge 凭证(无→unscored)。
- **Placeholder 扫描**:无 TODO;示例 bundle 的占位产物明确标注是模板。
