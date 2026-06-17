# Phase 6 — 公开面（公共面 / public face）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: subagent-driven-development（implementer→spec审→质量审 per task），最后 opus 全量 review。Steps 用 checkbox（`- [ ]`）跟踪。

**Goal:** 把 BrainPilotBench 做成可引用、策展、抗污染、**由我们主导**的 benchmark：不可变命名发布（`registry.json` 冻结任务集 → `BrainPilotBench-vX`）、provenance 一等字段（`created_at`）、策展式 intake（提案走 Issue、**不在 CI 跑陌生人脚本**），并修掉一直把示例 exec 任务挡在贡献门外的递归发现 bug。

**哲学（本期定调）：封闭策展型 benchmark。** 我们策展 intake + 我们跑分 + v1/v2 命名快照——三件事自洽。created_at 因此从「cutoff 过滤轴」降级为「便宜的 provenance 元数据」（不建 filter）。公开 leaderboard 基础设施 + 外部 SUT 注入**不在本期**，声明为下一阶段关键路径（SUT adapter seam）。结构化 JSON 输出（spec §6）已由 `scores.json` 满足，无新工作。

**Architecture:**
- `src/discover.ts`（新，可测）：`discoverTaskDirs(roots, {includeExamples})` 递归发现 + 多根 + 跳过 `node_modules`/dot-dir，遇含 `task.yaml` 的目录即记录不再下钻。「canonical」= 相对根的路径无任何段以 `_` 开头。
- `src/registry.ts`（新）：纯函数 `buildRelease`/`addRelease`(拒重名)/`loadRegistry`/`saveRegistry`/`verifyRegistry`(注入 git/loader 依赖→离线可测) + 类型 `Registry`/`RegistryRelease`/`FrozenTask`。
- `src/task.ts` + `src/loader.ts`：`createdAt?: string`（可选→不引发 fake-meta ripple；loader 解析 `created_at`）。
- `src/validate.ts`：`createdAt` 缺失或非 `YYYY-MM-DD` → error（与 canary 同属公开污染防御，硬门）。
- `src/cli.ts`：`listTaskDirs` 改用 discover；`--tasks a,b` 多根；新增 `freeze <name>` + `registry verify`；usage 更新。
- 治理（文档 + 仓配置，无代码）：`CONTRIBUTING.md`、`.github/ISSUE_TEMPLATE/task-proposal.yml`、`.github/CODEOWNERS`、README 章节。

**Tech Stack:** TypeScript（NodeNext, strict）→ `tsc` → `dist/`；`node --test`；**零新运行时依赖**（Node 内置 `fs`/`path`/`child_process` + 已有 `yaml`）。Node ≥ 22。git 操作只读（`rev-parse`/`cat-file -e`），freeze 绝不建/推 tag。

## Global Constraints

- **零新运行时依赖**；构建 `npm run build`、测试 `npm test`、typecheck `npm run typecheck`。
- TS-TDD：引用不存在导出→build RED；逻辑未实现→test RED。跑命令前 `. "$HOME/.nvm/nvm.sh"`（Node v24）。
- 提交信息结尾固定：`Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`
- 当前在 `feat/phase6-public-face`（base `main`@fbf6f7a，含 Phase 1-5）。现有 **101 单测**必须全绿，含 Phase 1 `blankScoresheet` 逐字节 golden。
- **行为变更（Task 2）**：递归发现会让 `validate all` 纳入 `_example/exec-task`（这是目的——补 Phase 4「CI 跑 0 个 exec task」缺口）；但 `list` 仍只 2 个 canonical 任务（`_` 前缀排除）。推任何东西前先本地 `validate all` 绿。

## 文件结构（本计划落子）

| 文件 | 职责 |
|---|---|
| `src/task.ts` | 修改。`TaskMeta` 加可选 `createdAt?: string` |
| `src/loader.ts` | 修改。`loadTask` 解析 `created_at`→`createdAt` |
| `src/validate.ts` | 修改。`createdAt` 缺失/非法日期→error |
| `src/discover.ts` | 创建。递归 + 多根任务发现 |
| `src/discover.test.ts` | 创建。递归/下划线过滤/多根/跳过 node_modules |
| `src/registry.ts` | 创建。冻结发布纯核心 + load/save + verify |
| `src/registry.test.ts` | 创建。build/addRelease 拒重名/verify 抓漂移 |
| `src/cli.ts` | 修改。discover 接入 + `--tasks a,b` + `freeze`/`registry verify` |
| `src/index.ts` | 修改。导出 discover + registry |
| `package.json` | 修改。exports 加 `./discover` `./registry` |
| `.github/workflows/validate.yml` | 修改。加 `registry verify`（registry.json 存在才跑） |
| `CONTRIBUTING.md` | 创建。策展 intake + 三 version 词汇表 + 污染 checklist |
| `.github/ISSUE_TEMPLATE/task-proposal.yml` | 创建。结构化提案表（无代码） |
| `.github/CODEOWNERS` | 创建。`tasks/`+`registry.json`+`categories.yaml`→维护者 |
| `README.md` | 修改。Governance / Releases / 「我们跑分」+ SUT-next 章节 |

> 复用不改：`loadTask`/`loadCategories`/`requiredMetricsFor`。`registry.json` 的 task-set 版本 ≠ task `version` ≠ npm `@brainpilot/bench` 版本（文档钉死区分）。

---

## Task 1: created_at 一等字段（provenance）

**Files:** Modify `src/task.ts`、`src/loader.ts`、`src/validate.ts`；Test `src/loader-createdat.test.ts`、扩 `src/validate.test.ts`。

- [ ] **Step 1 写失败测试** `src/loader-createdat.test.ts`：构造真 task.yaml（`created_at: 2026-06-15` 不带引号）→ `loadTask(dir).meta.createdAt === "2026-06-15"`；无 `created_at` → `meta.createdAt === undefined`。validate.test.ts 加：缺 createdAt → 出 error；`created_at: garbage` → 出 error；合法日期 → 无 createdAt 相关 error。
- [ ] **Step 2 build RED**：`createdAt` 不在 TaskMeta。
- [ ] **Step 3 `task.ts`**：`requires` 行附近加 `/** ISO 日期(YYYY-MM-DD);污染防御一等轴(provenance)。 */ createdAt?: string;`（**可选**，不引发 fake-meta ripple）。
- [ ] **Step 4 `loader.ts`**：meta 字面量加 `createdAt: metaRaw.created_at != null ? String(metaRaw.created_at) : undefined,`。（注：YAML 1.2 core 把 `2026-06-15` 当字符串，eemeli/yaml 默认即此；若测出是 Date，`String()` 会变丑→改成正则取 `^\d{4}-\d{2}-\d{2}`。测试会暴露。）
- [ ] **Step 5 `validate.ts`**：`validateTaskSchema` 加：`if (!m.createdAt) error("缺 created_at(provenance/污染防御)")` `else if (!/^\d{4}-\d{2}-\d{2}$/.test(m.createdAt)) error("created_at 非法,需 YYYY-MM-DD")`。
- [ ] **Step 6 GREEN**：build+test 全绿；3 个种子任务仍 `validate` 通过（都已有 created_at）。`node dist/cli.js validate all` exit 0。
- [ ] **Step 7 提交**：`feat(task): created_at 提成一等 provenance 字段(解析+validate 校验,不建 filter)`

---

## Task 2: 递归 + 多根任务发现（行为变更，谨慎）

**Files:** Create `src/discover.ts`、`src/discover.test.ts`；Modify `src/cli.ts`。

**Interfaces:** `discoverTaskDirs(roots: string[], opts?: { includeExamples?: boolean }): string[]`（递归找含 `task.yaml` 的目录；遇到即记录不再下钻；跳过 `node_modules` 与 `.`/dot 目录；`includeExamples` 默认 false=排除任何路径段以 `_` 开头的目录；多根去重，按路径排序稳定）。

- [ ] **Step 1 写失败测试** `src/discover.test.ts`（tmpdir 造树）：①嵌套 `a/b/task.yaml` 被找到；②`_example/x/task.yaml` 默认排除、`includeExamples:true` 纳入；③不下钻进任务内部（任务目录里的 `checks/` 不被当任务）；④两根合并去重；⑤跳过 `node_modules`/`.git`；⑥不存在的根→跳过不抛。
- [ ] **Step 2 build RED**：`./discover.js` 不存在。
- [ ] **Step 3 写 `src/discover.ts`**：`readdirSync(..,{withFileTypes})` 递归；命中 `task.yaml` 即 push 并 return（不再下钻）；skip 名以 `.` 开头或 `node_modules`；canonical 过滤 = 相对每个 root 的路径段无 `_` 开头（除非 includeExamples）。
- [ ] **Step 4 改 `cli.ts`**：`const taskRoots = (arg("--tasks","tasks")!).split(",").map(s=>s.trim()).filter(Boolean)`；`listTaskDirs()` → `discoverTaskDirs(taskRoots, {includeExamples:false})`。新增 `listAllTaskDirs()` = `{includeExamples:true}` 给 `validate all` 与 by-id 查找用。规则：`list`/`run all`/`fetch all`/`leaderboard` catById → canonical-only；**`validate all` → all（含示例）**；`run <id>`/`score`/`validate <id>` by-id 查找 → all。
- [ ] **Step 5 GREEN + 行为验证**：build+test 全绿；`node dist/cli.js list` 仍恰 2 行；`node dist/cli.js validate all` **现在含 `example-exec-task`** 且 exit 0（Oracle/NOP 门真跑且绿——这是补上的回归守卫）。
- [ ] **Step 6 提交**：`feat(discover): 递归+多根任务发现(修 1 层扫描漏嵌套;validate all 纳入示例 exec 门)`

---

## Task 3: registry 冻结发布纯核心

**Files:** Create `src/registry.ts`、`src/registry.test.ts`。

**Interfaces:**
- `interface FrozenTask { id: string; version: string; category?: string; createdAt?: string }`
- `interface RegistryRelease { name: string; commit: string; ref?: string; frozenAt: string; tasks: FrozenTask[] }`
- `interface Registry { releases: RegistryRelease[] }`
- `buildRelease(name, commit, ref, frozenAt, tasks: Task[]): RegistryRelease`（纯，Task→FrozenTask 投影）
- `addRelease(reg, release): Registry`（纯；重名→throw，**不可变**）
- `loadRegistry(path): Registry`（不存在→`{releases:[]}`；坏 JSON→throw 清晰）；`saveRegistry(path, reg)`（2-space JSON）
- `verifyRegistry(reg, deps: { taskById: Map<string, Task>; commitExists: (sha:string)=>boolean; categoryExists:(c:string)=>boolean }): Array<{ release:string; ok:boolean; problems:string[] }>`（纯；逐 release 检查：每 task 仍存在、version 匹配、category 已知、commit 可达；release 名唯一）

- [ ] **Step 1 写失败测试** `src/registry.test.ts`：buildRelease 投影正确；addRelease 重名 throw；verify——全绿用例 ok=true；删一个 task → problems 含「missing」；version 漂移 → problems 含「version」；commitExists=false → problems 含「commit」；未知 category → problems。load/save tmpdir round-trip。全部注入 fake deps，离线。
- [ ] **Step 2 build RED**；**Step 3 写 `src/registry.ts`**。
- [ ] **Step 4 GREEN**：build+test 全绿。
- [ ] **Step 5 提交**：`feat(registry): 冻结发布纯核心(buildRelease/addRelease拒重名/verifyRegistry注入依赖)`

---

## Task 4: CLI `freeze` + `registry verify` + CI 接线

**Files:** Modify `src/cli.ts`、`src/index.ts`、`package.json`、`.github/workflows/validate.yml`。

**Interfaces:** `bp-bench freeze <name> [--ref <tag>] [--registry registry.json]`；`bp-bench registry verify [--registry registry.json]`。

- [ ] **Step 1 `cli.ts` 加 git helper**：`gitHead()`=`git rev-parse HEAD`（trim）；`gitCommitExists(sha)`=`git cat-file -e <sha>^{commit}` 退出码。失败给清晰错误（非 git 仓 / git 缺失）。
- [ ] **Step 2 `freeze` 分支**：收集 canonical 任务（`discoverTaskDirs(roots,{includeExamples:false})`→loadTask）→ `buildRelease(name, gitHead(), arg("--ref"), new Date().toISOString().slice(0,10), tasks)`；`loadRegistry`→`addRelease`（重名 throw→打印「发布名已存在,不可覆盖(请发新版本)」exit 1）→`saveRegistry`。打印 `wrote registry.json: <name> @ <sha7>, N tasks`。
- [ ] **Step 3 `registry verify` 分支**（`cmd==="registry" && argv[1]==="verify"`）：`loadRegistry`→建 `taskById`（all 任务 loadTask）+`commitExists`(git)+`categoryExists`(loadCategories)→`verifyRegistry`。逐 release 打印 ✓/✗ + problems；任一 ✗ → exit 1。registry.json 不存在 → 打印「无 registry.json」exit 0（CI 友好）。
- [ ] **Step 4 usage + `index.ts` 导出 + `package.json` exports** 加 `./discover` `./registry`。
- [ ] **Step 5 `.github/workflows/validate.yml`** 末尾加步：`- name: registry verify` `run: node dist/cli.js registry verify`（registry.json 不存在时 cli 自身 exit 0，无需 shell guard）。
- [ ] **Step 6 全量 + e2e**：typecheck+build+test 全绿（~116）；e2e：临时 registry 路径 `freeze test-v1` → `registry verify` ✓；手改某 task version → verify ✗ 且 exit 1；`freeze test-v1` 再来一次 → 拒重名 exit 1。API 三函数 typeof。
- [ ] **Step 7 提交**：`feat(cli): freeze 冻结发布 + registry verify(绑 commit/可选 ref,拒重名,CI 接线)`

> 注：freeze 记录 `git rev-parse HEAD` 的 commit + 可选 `--ref`（你已 push 的 tag，如 `tested/...`）；**绝不自行建/推 tag**。冻结一个未 push 的 commit 是废的——verify 的 `commitExists` 在你本地能过、在干净 CI clone 上会 ✗，提醒你去 push/tag。

---

## Task 5: 治理文档 + 仓配置（无代码）

**Files:** Create `CONTRIBUTING.md`、`.github/ISSUE_TEMPLATE/task-proposal.yml`、`.github/CODEOWNERS`；Modify `README.md`。

- [ ] **Step 1 `CONTRIBUTING.md`**：①策展 intake 模型——提案走 **Issue**（科学问题 + 数据来源 + rubric 草稿，**不含 task.yaml/check.sh/任何可执行脚本**），**我们**亲手集成成 canonical commit；②为什么这么做（污染控制 + construct validity 需编辑判断，不能自助 PR 自动合并）；③入库前污染 pre-check checklist（web 搜原题/答案是否已公开可背）；④**三 version 词汇表**：task `version`（单题 spec）/ registry `vN`（题集快照）/ npm `@brainpilot/bench@0.0.x`（框架）。
- [ ] **Step 2 `.github/ISSUE_TEMPLATE/task-proposal.yml`**：GitHub issue form（字段：领域/category、科学问题、期望产物、数据来源+体量、rubric 维度草稿、为何不易污染/原创性、参考文献）。无代码字段。
- [ ] **Step 3 `.github/CODEOWNERS`**：`/tasks/ @NeuroAIHub/maintainers`、`/registry.json @NeuroAIHub/maintainers`、`/categories.yaml @NeuroAIHub/maintainers`。（占位 team，用户改。）
- [ ] **Step 4 `README.md`** 章节：**Governance**（策展制、指向 CONTRIBUTING、需在仓 settings 开 branch protection + require review，列明设置）；**Releases (registry.json)**（freeze/verify 用法、命名快照不可变、绑 git ref）；**Scoring is run by maintainers**（自报分可作弊→我们跑分；外部系统接入靠 SUT adapter，是下一阶段关键路径）。
- [ ] **Step 5 验证 + 提交**：`node dist/cli.js list`/`validate all` 不受文档影响仍正常。提交：`docs(governance): 策展 intake(Issue 提案)+CODEOWNERS+README Releases/Scoring 章节`

---

## 验收标准（Phase 6 完成定义）

- `npm run typecheck && build && test` 全绿，**~116 单测**（101 + discover/registry/createdAt），`# fail 0`，含 Phase 1 golden 逐字节。
- **零新依赖**。
- `bp-bench list` 仍恰 2 canonical 任务；**`validate all` 现纳入 `example-exec-task` 且绿**（Oracle/NOP 回归守卫落地）。
- `freeze`→`registry verify` 端到端 round-trip；version 漂移/dangling commit/重名被 verify 抓到并 exit 1。
- `created_at` 解析进 `TaskMeta` + validate 硬校验；**不建 `--since` filter**。
- 治理：CONTRIBUTING（策展 intake）+ Issue 提案模板 + CODEOWNERS + README 三章节落地。
- 公开 leaderboard 基础设施 + 外部 SUT 注入**明确不做**，README 声明为下一阶段（SUT adapter seam）。
- 最后跑 opus 全量对抗 review（同 Phase 5）再 merge。

## 自检记录（writing-plans self-review）

- **设计覆盖 spec §9 Phase 6**：registry.json 冻结任务集（Task3/4）、entry-point 插件发现→**改为策展 Issue intake**（用户决策，Task5；§10 反模式「过早拆包直到真有 out-of-tree 贡献者」支撑——现 0 贡献者）、污染刷新节奏→**hybrid 命名快照 + created_at provenance**（Task1 + registry，**不建 cutoff filter**，用户确认慢迭代下冗余）。明确不做：node_modules 插件扫描、`--since` filter、公开 leaderboard 提交基础设施、包/仓拆分。
- **三个 concern 已落地**：①不在 CI 跑陌生人脚本 = Issue intake（提案无可执行代码）；②created_at 自报不可信 → registry `frozenAt` 由 freeze 盖戳（非 task 自报）；③freeze 绑 ref 防指向未 push commit（verify 的 commitExists）。
- **类型一致**：`FrozenTask`/`RegistryRelease`/`Registry`、`buildRelease`/`addRelease`/`verifyRegistry(deps)`、`discoverTaskDirs(roots,opts)` 跨 Task 一致；复用 `Task`/`loadTask`/`loadCategories`/`requiredMetricsFor` 不改签名。`createdAt?` 可选避免 fake-meta ripple（与 Phase 5 必填 `version` 的有意不同——version 由 loader 必定填值,createdAt 缺省须被 validate 抓,故可选+门校验）。
- **行为变更已隔离**：Task 2 递归发现是唯一行为变更,用「canonical(_ 排除) vs all(validate 用)」一条规则覆盖；本地 `list`=2 / `validate all`=含示例 双向验证写进 Step 5。
- **Placeholder 扫描**：CODEOWNERS team 名是占位（已标注用户改）；无 TODO/TBD。
