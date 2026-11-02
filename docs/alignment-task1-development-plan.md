# Alignment 任务一：开发执行计划

日期：2026-10-23；状态更新于 2026-11-02。合成脚手架已实现；真实服务器后端代码已补齐，尚未安装真实环境、下载模型/脑数据或执行验证。服务器步骤见 [运行说明](../tasks/alignment/SERVER_RUNBOOK.md)。本轮按用户要求只做本地静态检查，不能将此前合成测试结果当作新后端的验收。任务二不在本计划的原始范围内。

本计划沿用已讨论的任务定位：给定固定模型、指定层的缓存表示及预处理脑响应，让 Agent 根据研究目标完成正确、可复现的 alignment 分析。Brain-Score 提供科学方法，BrainPilotBench 评价 Agent 的分析实施能力。

## 1. 首版范围与默认选择

| 项目 | 首版计划 |
|---|---|
| 能力目标 | 数据理解、刺激匹配、实验组织、官方方法使用、计算复现及结果解释 |
| 拟议 task ID | `alignment-pereira2018-analysis` |
| 拟议 category | `alignment-analysis` |
| 拟议 task version | `0.1`，在验收完成后冻结 |
| 数据 | Pereira2018 的 384 句实验，使用官方预处理语言网络响应 |
| 正式模型 | 建议 `meta-llama/Llama-3.2-1B`；准备数据前锁定权重及 tokenizer revision |
| 指定层 | 建议 `model.layers.8`，明确为从零编号的 block 8 输出；固定选择，不寻找最佳层 |
| 工程 smoke 模型 | `distilgpt2`，仅验证适配路径，不替代正式模型结果 |
| 科学问题 | 指定表示对未见段落的脑响应具有怎样的预测能力？ |
| 科学协议 | 冻结 Brain-Score Language commit `3b4fde5d6f53a69c652c7a1128397549995547b0` 的 `Pereira2018.384sentences-ridge` 行为 |
| Agent 主指标 | `analysis_success`，单个任务实例取 0 或 1；多实例/多次运行报告成功率 |
| Agent 运行资源 | CPU、离线、固定依赖；缓存准备阶段与 Agent 阶段分开 |
| 首版不包含 | MCP、层搜索、模型训练/微调、原始 MRI 预处理、开放式选择主指标、多模态扩展 |

以上模型、层和任务名称是建议默认值，不是已经生成的数据绑定。阶段 P0 将这些值、实际资源限额及版本写入契约；后续变更须更新任务或协议版本。

## 2. Agent 题面与自由度

建议题面：

> 给定指定模型层对句子的缓存表示、刺激元数据及多位受试者的预处理语言网络脑响应，使用提供版本的 Brain-Score 方法评估该表示对未见段落的预测能力。提交可重跑的分析程序、逐折结果与简短报告，说明原始分数、ceiling 校正结果及其解释边界。

固定模型、层、脑区、上下文、pooling、科学协议和评价规则。Agent 决定如何读取和整理输入、构造数据结构、调用工具、实施检查及组织报告。允许补充分析，但补充分析不改变主分数。

提供字段文档和通用 Brain-Score API 说明，不默认提供本任务的完整端到端答案。保留真实文件组织差异，不故意制作坏文件或含糊字段来制造难度。若通用模板能轻易覆盖全部实例，将任务定位为基础分析能力检查，不宣称开放科研发现。

## 3. 必须先冻结的科学契约

`protocol.json` 记录以下内容：

1. 上游代码 commit、benchmark 注册 ID、benchmark version、模型与 tokenizer revision。
2. 层的准确模块路径与读取位置、模型推理精度、上下文拼接和截断规则、last-token pooling。
3. 刺激 ID、原始呈现顺序、passage/story 分组及实验筛选规则。
4. 受试者与 neuroid 身份、脑区、缺失值及排除规则；不自行改为另一种受试者聚合。
5. 与上游一致的分组交叉验证、随机种子、实际折分 ID，以及训练内正则参数选择机制。
6. 原始相关性、跨 neuroid/折的聚合、ceiling 来源、归一化与裁剪行为。
7. 各输出字段的数值精度、比较方法和校准后的容差。

首版保留上游协议，不能额外加入标准化、PCA、另一个 ridge 实现、不同聚合或拆分，并仍称其为同一结果。若确认上游问题需要修正，应记录补丁、验证影响，并建立独立 profile，不能静默修改。

## 4. 数据包契约

公开工作区提供输入、说明和环境；可信评测端另行保留参考结果和重跑用例。大数组、权重和完整参考结果不进 Git。

建议每个分析输入包包含：

| 文件 | 内容 |
|---|---|
| `manifest.json` | schema、来源、文件哈希、模型/层绑定、轴定义、协议 ID |
| `stimuli.csv` | `stimulus_id`、文本、实验、passage/story、呈现顺序 |
| `model/features.npy` | 指定层的 `N × D` float32 缓存 |
| `model/stimulus_ids.json` | 特征行到刺激的显式对应 |
| `brain/responses.nc` | 官方 assembly 的数值及 subject/neuroid/刺激元数据 |
| `protocol.json` | 冻结的计算协议 |
| `folds.json` | 按刺激 ID 表达的参考折分及分组验证信息 |
| `ceiling/` | 本协议实际使用的官方 ceiling 对象及来源哈希 |
| `DATA_DICTIONARY.md` | 轴、字段、缺失值、来源及使用说明 |

文件名是拟议接口，P0 冻结后保持稳定。若用其他无损格式替代 NetCDF，须保留坐标、排序和缺失值语义并通过等价性验证。

重要边界：这是分析复现任务。正式重跑时，提交程序需要收到该用例的 X 和 Y，才能执行交叉验证、拟合并计算结果；隐藏的是开发阶段未提供的重跑实例和参考答案。不能宣称提交程序从不接触 CV 测试折的 Y。通过逐折预测对照和功能性检查评价是否实现了正确的训练/测试使用逻辑。

## 5. 提交接口与输出

统一入口：

```text
python submission/analyze.py --inputs /inputs --output /output
```

程序必须使用传入数据包，不得依赖维护者路径或以另行下载的原始数据替代传入数据。评分阶段禁网，依赖预装；输出写到独立目录，输入和提交文件只读。

必需提交：

- `submission/analyze.py` 及它需要的辅助源码。
- `analysis_config.json`：实际选择的模型、层、方法、协议及版本。
- `results/summary.json`：原始指标、归一化指标、ceiling、覆盖情况和协议绑定。
- `results/fold_scores.csv`：按 fold/neuroid 身份记录的结果，具体必需列由 P0 冻结。
- `results/predictions.npz`：逐折预测与样本/测量单元 ID；重叠测试样本用 fold ID 区分。
- `report.md`：方法、结果、检查、限制。

评测器既检查 Agent 保存的公开运行结果，也在新输出目录重新执行程序。`meta.json` 必须绑定准确 taskVersion。

## 6. 客观评分与失败语义

单个正式实例的 `analysis_success = 1` 需要同时满足：

1. 必需文件和接口有效，程序能在规定环境完成。
2. 样本覆盖、刺激匹配、脑区/neuroid 集合和分组满足契约。
3. 逐折预测、逐折指标和最终聚合与可信参考在预定容差内一致。
4. 重跑与额外正确性用例通过，未修改输入或提交文件。

`analysis_success = 0` 表示提交可评价，但分析计算不符合要求。模型的原始 alignment 低不导致 Agent 低分。另输出参考匹配率、最大数值偏差、用时等诊断；没有可计算的误差时，不写 NaN/Infinity。

报告解释独立检查：是否区分 raw/normalized score，是否描述正确协议，是否将预测能力过度解释为机制等同。首版不把 LLM 文风评分混入主指标。

区分失败类型：

- 缺必需提交文件：沿用 submission_invalid。
- 提交程序语义错误、无有效结果或在既定限额内运行失败：由任务控制程序产生可评价的失败记录，主分数为 0。
- 数据损坏、评测镜像不可用、评测基础设施失败：标记 unscored/scoring_failed，不算 Agent 零分。
- 外部 scorer 自身超时：视为基础设施未完成；worker 限额应早于外层超时，确保控制程序能记录正常的任务失败。

可信控制程序单独计算分数、发出 BPB_SCORES。提交 stdout 不能成为可信得分来源。空提交不输出有效评分块，以兼容现有 NOP 校验；可执行但计算错误的提交可以正常产生零分。

## 7. 分阶段执行

### P0 — 冻结规格与准备约束

工作：完成题面、协议、输入/输出 schema、文件组织、评分语义；确认数据与模型获取路线、缓存分发条件、目标 CPU 平台和预处理说明；解析模型 revision。正式输入和检查环境不得沿用未固定的 main/latest。

交付：`contract.json`、`protocol.json`、schema、题面草稿、依赖/来源清单。

验收：给两位实现者同一规格，应能明确什么结果算正确；不存在“挑哪个分数高就用哪个”的空间。尚未具备真实数据验收前，不将任务登记为 runnable。

### P1 — 打通官方参考路径与结果追踪

工作：创建隔离 Python 环境，锁定 Brain-Score 和 brainscore-core 等传递依赖；用小模型及正式实验验证官方评分。增加不改变数学行为的追踪适配，记录逐折预测和分数，证明追踪版与原始官方入口一致。用小型可手算/可独立计算的 fixture 验证数组对应和聚合。

交付：维护者参考程序、锁定环境、参考结果 schema、首份等价性记录。

验收：官方入口与追踪路径一致；已明确哪些结果可从 Score 属性取得，哪些需捕获预测；不会仅凭示例脚本输出推断成功。

### P2 — 生成正式缓存与输入包

工作：获取并验证 Pereira 数据及固定 Llama checkpoint；按官方刺激上下文生成指定层特征；导出带完整坐标的输入包，生成 SHA-256、来源和文件大小记录。首版只要求指定层，不开展全层搜索。

交付：仓外公开输入包、manifest、可重跑的准备脚本、缓存一致性报告。

验收：先检查若干完整 passage 的实时/缓存特征，再对完整正式实例比较实时模型路径与缓存适配路径的 raw、ceiling 和归一化结果；差异须在经验证的精度范围内。通过后冻结数据绑定。

### P3 — 建立可信参考答案与检查用例

工作：在目标 CPU 环境重复运行参考程序，记录数值波动、内存和耗时，冻结容差与资源限额。建立公开小示例、正式数据参考及不向 Agent 提供答案的工程检查。

检查至少覆盖：

- 按 stimulus ID 正确重排后结果保持一致。
- 不同合法轴顺序/文件组织经正确转换后结果一致。
- 小型新生成 fixture 上计算结果正确，防止硬编码公开总分。
- 缺样本、重复 ID、非法形状、非有限值时按公开契约处理。
- 对指定 CV 折，仅改变该折测试 Y 时，该折预测不应改变；指标可以改变。这是工程正确性测试，不作为真实科研结果。
- 数据包选择变化时程序确实使用传入数据，不能回退到全局缓存中的另一份数据。

交付：参考结果包、检查清单、容差与资源报告、正负参考提交。

验收：正确实现稳定通过；错配刺激、训练内评分、错误聚合、硬编码结果等已知错误实现被检出。额外重排/合成 fixture 只计为正确性检查，不宣称独立科学实验。

### P4 — 实现隔离评分器

工作：可信父进程加载检查用例和参考答案，在受限 Docker worker 中重跑提交；挂载该用例的 X/Y，但不挂载参考答案、其他用例或维护者凭证；检查输出 schema、逐折结果、提交不可变性并生成评分报告。

交付：`checks/check.sh`、可信控制程序、worker、Dockerfile、环境锁、评分报告 schema。

验收：正确参考提交得到 1；有效错误实现得到 0；空提交被拒绝；缺镜像/损坏输入被识别为评测失败；超时能清理 worker；提交打印伪评分块不改变得分。不增加绕过真实计算的 oracle_mode。

### P5 — 接入 BrainPilotBench

工作：完成 README、task.yaml、prompt、data.lock、setup.sh、solution 和检查文档；新增 category 与目录注册；沿用现有 exec-script scorer、artifact collection、submission verification 和 leaderboard，不优先修改通用 runner。

拟议目录：`tasks/alignment/alignment-pereira2018-analysis/`。

需要联动的现有文件：

- `categories.yaml`：新增 alignment-analysis，主列 analysis_success。
- `scripts/check-collection.mjs`：允许 alignment 目录并检查新任务契约。
- `scripts/refresh-collection.mjs`：如记录真实参考验收，加入有证据支持的状态，避免手填夸大验证范围。
- `tasks/catalog.json`：用生成器刷新。
- `.github/workflows/validate.yml`：新增小型、离线的任务检查；不在普通 CI 下载完整模型或科研数据。
- README/任务索引：按验收状态更新导航和数量。

验收：list/prepare/run/manual resume/submit verify/score/leaderboard 链路可用；schema、collection、catalog、现有回归及 docs smoke 均通过。完整 Oracle/NOP 只在已准备相应环境与数据时运行。

### P6 — 小规模 Agent 验收与难度校准

工作：对比维护者参考、固定通用模板及 Agent 提交；所有系统用同一公开输入、文档和资源。先做调试性试跑，再根据结果波动制定正式重复次数；不把一次成功当成稳定能力，也不在本阶段声称统计功效已充分。

交付：真实运行 bundle、错误类型统计、计算成本、任务可辨别性记录。

验收：评分器能够区分真实的组织/计算错误；任务能在声明资源内完成；说明足够清晰。若模板完全解决任务，将其标为基础能力检查，或重新讨论真实任务范围，不靠随机限时、缺文档或数据陷阱提难度。

### P7 — 整理贡献材料

工作：整理文字 Task Proposal、科学来源、数据访问说明、复现记录和已知限制。按仓库 CONTRIBUTING 流程，提案以说明和数据指针为主，正式任务由维护者审核集成。

交付：可审阅提案、实现清单、验收证据及准确的完成状态。

## 8. 执行顺序和完成标准

依赖顺序：`P0 → P1 → P2 → P3 → P4 → P5 → P6 → P7`。

当前最先执行的切片应为 P0–P1：先证明科学协议、参考计算和逐折追踪可用，再投入正式缓存与评分器开发。

达到首版可用需要同时具备：

- [ ] 冻结、可解释的任务与科学契约。
- [ ] 正式模型/数据哈希及可重跑准备流程。
- [ ] 实时/缓存完整实例等价性证据。
- [ ] 公共输入与评测参考的明确边界。
- [ ] 可在相同契约的新输入上运行的提交接口。
- [ ] 基于重跑及逐折结果的客观评分。
- [ ] 正确、错误、空提交和基础设施失败的检查。
- [ ] BrainPilotBench 全链路集成及回归检查。
- [ ] 至少完成真实 Agent 路径的调试性验收，后续稳定性证据单独标注。
- [ ] 贡献状态不混淆工程验收与正式 Agent benchmark 结果。

## 9. 参考入口

- [已核查的 Brain-Score Language 版本](https://github.com/brain-score/language/tree/3b4fde5d6f53a69c652c7a1128397549995547b0)
- [Pereira benchmark](https://github.com/brain-score/language/blob/3b4fde5d6f53a69c652c7a1128397549995547b0/brainscore_language/benchmarks/pereira2018/benchmark.py)
- [Hugging Face 特征接口](https://github.com/brain-score/language/blob/3b4fde5d6f53a69c652c7a1128397549995547b0/brainscore_language/model_helpers/huggingface.py)
- [Encoding metric](https://github.com/brain-score/language/blob/3b4fde5d6f53a69c652c7a1128397549995547b0/brainscore_language/metrics/linear_predictivity/metric.py)
- [本仓库贡献规则](../CONTRIBUTING.md)

本文随任务一代码纳入版本控制；`.gitignore` 已显式允许跟踪该计划。
