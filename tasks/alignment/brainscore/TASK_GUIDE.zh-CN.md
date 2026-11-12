# Brain-Score 扩展任务的 Agent 工作与输入数据

更新日期：2026-11-11。本文对应 [instances.json](instances.json) 中的 **24 个实例：18 个 T1 单模型复现、6 个 T2 双模型比较**，覆盖 6 个数据来源家族、9 个官方 benchmark。它们是固定分析协议的不同实例，不代表 24 个独立数据集。

Agent 的工作是读取给定数据、编写并运行分析程序、复现科学指标、提交可核对的结果和结论。**候选模型特征已经算好；Agent 需要拟合规定的预测映射或计算行为相关，而不是训练候选模型。** Agent 的成绩是分析是否正确，候选模型的 Brain-Score 高低是科学结果。

当前真实输入已验证的是 **Pereira384 × distilgpt2**；其余组合已经定义输入契约并通过合成数据流程验证，尚未全部准备真实数据包。下面的“提供数据”描述任务交付时的内容，不表示这些文件现在均已就绪。完整状态见 [VALIDATION.md](VALIDATION.md)。

官方外部参照已逐项核验：10 个语言组合有官网公布成绩；8 个视觉 public 组合尚未确认可直接用于当前配置的公开数值；6 个比较任务由本仓库定义。网页分数与严格评分参考的区别、具体数值和链接见 [基线核验](BASELINE_AUDIT.md)。

本文只覆盖本轮 Brain-Score 扩展；既有 A–F 任务另见 [A–F 中文说明](../TASKS_A_F_GUIDE.zh-CN.md)，既有 Task1、Task2 分别见 [Task1 契约](../REAL_TASK1_CONTRACT.md)和 [Task2 契约](../REAL_PROFILE_CONTRACT.md)。

## 1 Agent 和维护者分别负责什么

| 角色 | 负责内容 |
|---|---|
| 维护者 | 准备来源文件、刺激和固定版本模型；按官方预处理生成特征与响应缓存；冻结 ID、缺失掩码、划分、噪声上限及软件环境；验证缓存计算与官方原始流程等价 |
| Agent | 按 ID 对齐数据；遵循固定划分拟合 PLS 或 ridge，或直接计算阅读时间相关；保存逐折预测和指标；完成分组描述、模型比较和报告 |
| 评分器 | 用维护者参考结果核对提交产物，在隔离环境重跑 Agent 代码，并改变部分输入检查程序是否真正依赖数据 |

任务提供预计算模型特征、处理后的实验响应和协议元数据。原始图片、模型权重、原始连续 ECoG 信号或原始四维 fMRI 不是这批缓存分析任务的必需交付物。来源中保留的刺激信息、文本上下文和测量坐标会随元数据提供。

科学交叉验证中的测试折响应也对 Agent 可见；Agent 仍须只在规定训练折拟合预测映射。维护者参考答案和评分用控制输入不随任务发给 Agent。

## 2 每个来源提供什么数据

下表的 X 是候选模型输出，Y 是实验测量。N 表示刺激条目数，D 表示特征维数，U 表示测量单元数；真实规模由对应数据包记录，不把私有数据或论文总体规模当作当前公开子集规模。

| 来源与官方 benchmark | X 和 Y 的含义 | 必须保留的信息 | Agent 的主要工作 |
|---|---|---|---|
| MajajHong2015：`MajajHong2015public.V4-pls`、`MajajHong2015public.IT-pls` | X：图片对应的 pixels 或 AlexNet 特征，N × D；Y：猕猴 V4 或 IT 神经元响应，N × U | 图片 ID、脑区、神经元 ID、`object_name`；官方时间和重复测量处理结果 | 用 PLS 预测留出图片的神经响应，计算 V4 或 IT 分数及物体类别分组描述 |
| FreemanZiemba2013：`FreemanZiemba2013public.V1-pls`、`FreemanZiemba2013public.V2-pls` | X：纹理／噪声图片对应的 pixels 或 AlexNet 特征，N × D；Y：猕猴 V1 或 V2 神经元响应，N × U | 图片和神经元 ID、`texture_type`、刺激条件；官方 50–200 ms 时间平均与重复平均结果 | 用 PLS 预测留出图片的神经响应，计算 V1 或 V2 分数及纹理类型分组描述 |
| Pereira2018：`Pereira2018.243sentences-ridge`、`Pereira2018.384sentences-ridge` | X：每个句子的固定语言模型层表示，N × D；Y：人类 fMRI 体素响应，N × U | 句子 ID、被试与体素 ID、`passage_label`、`story`、缺失响应；两个实验分别打包 | 按 story 划分，用 ridge 预测留出句子的体素响应，计算分数及被试／story 描述 |
| Fedorenko2016：`Fedorenko2016-ridge` | X：每个词在所属句子上下文中的固定层表示，N × D；Y：人类 ECoG 电极响应，N × U | 词 ID、`sentence_id`、被试与电极 ID、缺失响应 | 按 sentence_id 划分，用 ridge 预测留出句子的逐词电极响应，并报告被试覆盖和分数 |
| Blank2014：`Blank2014-ridge` | X：故事片段在对应故事上下文中的固定层表示，N × D；Y：人类 fMRI 功能兴趣区 fROI 响应，N × U | 片段顺序、`story`、被试与 fROI ID、缺失响应 | 按 story 划分，用 ridge 预测留出故事片段的 fROI 响应，并做被试／story 描述 |
| Futrell2018：`Futrell2018-pearsonr` | X：模型逐词 surprisal，N 维，单位为 bit；Y：人类逐词阅读时间，N × 被试数 | 词、句子和 story 坐标、被试 ID、`word_within_sentence_id`、模型与人的缺失掩码 | 排除句首词，按官方方式汇总人的阅读时间，与模型输出直接求相关，并做被试／story 描述 |

Pereira 的模型上下文按 `passage_label` 重置，交叉验证按 `story` 分组，两者不能混用。Futrell 的冻结实现按来源词序对全部词做一次上下文调用，不能自行改成每个故事重置。这些模型运行步骤由维护者在生成 X 时完成，Agent 使用缓存中已经固定的结果。

### 数据包长什么样

```text
INPUT_CONTRACT.md
inputs/
  manifest.json
  instance.json
  bundle.json
  case-00/
    manifest.json
    metadata.json
    provenance.json
    candidate.npy
    responses.npy
    response_valid.npy
    candidate_valid.npy   # 仅行为任务
  case-01/                # 多 case 的 T2 实例继续排列
  ...
```

一个 case 对应一个官方 benchmark 和一个候选模型。T1 含 1 个 case；T2 含 2 或 4 个 case。按 `bundle.json` 和各 case 的身份字段读取数据，不通过目录序号猜候选模型。

| 文件或字段 | Agent 获得的信息及用途 |
|---|---|
| `inputs/manifest.json` | 实例身份、文件清单与哈希、是否为合成数据 |
| `instance.json` | T1／T2 类型、benchmark 列表、候选模型比较顺序 |
| `bundle.json` | case 目录和对应缓存哈希 |
| `candidate.npy` | 神经任务的 X，形状 N × D；行为任务的逐词模型输出，形状 N |
| `responses.npy` | Y，形状 N × U；行为任务的 U 是被试数 |
| `response_valid.npy` | 与 Y 同形状的布尔掩码，保留真实缺失情况 |
| `candidate_valid.npy` | 行为输出是否有效的布尔掩码，形状 N |
| `metadata.json` | `candidate_presentation_ids`、目标行的 `presentations`、测量列的 `units`、来源坐标、候选配置、文本上下文及 `protocol` |
| `metadata.json` 中的 `protocol` | 官方计算规范、固定 train/test ID、排除项和 ceiling；ceiling 是提供的噪声上限，不要求 Agent 从头估计 |
| `provenance.json` 与 case 的 `manifest.json` | 来源、版本和缓存绑定信息，用于追溯具体输入 |

X 与 Y 的行序可能不同，须用显式 presentation ID 对齐。缺失响应不能擅自填零、补值或静默删除；测量单元身份也必须保留。

已验证的真实例子：Pereira384 × distilgpt2 的 X 为 **384 × 768**，Y 为 **384 × 12,155**，任务要求完成 10 折 ridge 分析。

## 3 三类分析流程要求 Agent 做什么

### V 视觉神经响应复现

1. 读取当前脑区的模型特征和神经响应，按 ID 对齐，保留缺失掩码和神经元身份。
2. 使用提供的 10 次分层随机划分，训练比例 0.9、随机种子 1；MajajHong 按 `object_name` 分层，FreemanZiemba 按 `texture_type` 分层。
3. 在每次训练划分上运行官方 `PLSRegression(n_components=25, scale=False)`，预测该次测试刺激的神经响应。
4. 保存每次划分的测试预测和逐神经元 Pearson r；每折先取神经元 r 的中位数，再对各折取均值得到 raw。
5. 计算 `normalized = raw² / ceiling`，保留未裁剪结果；该分数可能大于 1。
6. 按可用的被试与刺激类别坐标生成描述性结果，提交完整数值轨迹和报告。

pixels 使用固定 RGB 像素表示；AlexNet 层随脑区固定：V1 为 `features.2`，V2／V4 为 `features.7`，IT 为 `features.12`。Agent 不进行层搜索、特征选择或额外标准化。

### L 语言神经响应复现

1. 对齐固定层文本表示和体素、电极或 fROI 响应，核对上下文、分组和缺失值信息。
2. 使用提供的 GroupKFold 划分：Pereira 按 story、Fedorenko 按 sentence_id，各 10 折；Blank 按 story，共 8 折。官方划分使用 shuffle 和种子 1234。
3. 在训练折运行官方 `RidgeGCVTorch`，alpha 候选为 `0.001, 0.01, 0.1, 1, 10, 100, 1000`；不能用 sklearn `RidgeCV` 替代或用测试响应选参数。
4. 保存每折选用的 alpha、测试预测、单元相关和 ID。每折先取单元 r 的中位数，再对折取均值得到 raw。
5. 保存 `unclipped = raw / ceiling`，以及裁剪到 `[0, 1]` 的 normalized；按可用坐标生成被试和 story 描述。

distilgpt2 固定使用 `transformer.h.5`，gpt2-small 固定使用 `transformer.h.11`。特征是官方上下文下每个文本片段最后 token 的表示；模型、tokenizer 和预处理版本见 [candidates.json](candidates.json)。

### B 阅读时间行为复现

1. 对齐模型逐词输出与人类逐词阅读时间，保留源词序、被试身份和缺失掩码。
2. 排除 `word_within_sentence_id == 1` 的句首词；按官方缺失值语义对人的阅读时间取被试均值。
3. 将模型输出与人的均值直接做官方 Pearson 比较。官方 raw 为 **绝对值 r**，同时保留有符号 `rvalue` 和 `pvalue`；按提供的 ceiling 做语言类归一化。
4. 保存全部模型输出、响应有效掩码、纳入词掩码和词 ID；报告逐被试及逐 story 的有符号相关与有效词数。

这里的模型输出是 surprisal，单位为 bit，不能解释成毫秒。该任务没有拟合读出映射，也没有交叉验证折。描述性相关和上游 p-value 本身不构成额外的显著性结论。

## 4 全部 18 个 T1 单模型复现实例

每行是一项完整 task：使用第 2 节对应来源的数据，执行第 3 节指定流程，并提交第 6 节全部产物。

| Task ID | 响应数据 | 候选及固定表示 | Agent 执行流程 |
|---|---|---|---|
| `alignment-bs-majajhong2015-it-alexnet-reproduce` | MajajHong IT 神经元 | AlexNet `features.12` | V，复现 IT 分数 |
| `alignment-bs-majajhong2015-it-pixels-reproduce` | MajajHong IT 神经元 | pixels | V，复现 IT 分数 |
| `alignment-bs-majajhong2015-v4-alexnet-reproduce` | MajajHong V4 神经元 | AlexNet `features.7` | V，复现 V4 分数 |
| `alignment-bs-majajhong2015-v4-pixels-reproduce` | MajajHong V4 神经元 | pixels | V，复现 V4 分数 |
| `alignment-bs-freemanziemba2013-v1-alexnet-reproduce` | FreemanZiemba V1 神经元 | AlexNet `features.2` | V，复现 V1 分数 |
| `alignment-bs-freemanziemba2013-v1-pixels-reproduce` | FreemanZiemba V1 神经元 | pixels | V，复现 V1 分数 |
| `alignment-bs-freemanziemba2013-v2-alexnet-reproduce` | FreemanZiemba V2 神经元 | AlexNet `features.7` | V，复现 V2 分数 |
| `alignment-bs-freemanziemba2013-v2-pixels-reproduce` | FreemanZiemba V2 神经元 | pixels | V，复现 V2 分数 |
| `alignment-bs-pereira2018-243sentences-distilgpt2-reproduce` | Pereira 243 句实验 fMRI 体素 | distilgpt2 `transformer.h.5` | L，10 折，按 story 分组 |
| `alignment-bs-pereira2018-243sentences-gpt2-small-reproduce` | Pereira 243 句实验 fMRI 体素 | gpt2-small `transformer.h.11` | L，10 折，按 story 分组 |
| `alignment-bs-pereira2018-384sentences-distilgpt2-reproduce` | Pereira 384 句实验 fMRI 体素 | distilgpt2 `transformer.h.5` | L，10 折，按 story 分组 |
| `alignment-bs-pereira2018-384sentences-gpt2-small-reproduce` | Pereira 384 句实验 fMRI 体素 | gpt2-small `transformer.h.11` | L，10 折，按 story 分组 |
| `alignment-bs-fedorenko2016-ecog-distilgpt2-reproduce` | Fedorenko 逐词 ECoG 电极 | distilgpt2 `transformer.h.5` | L，10 折，按 sentence_id 分组 |
| `alignment-bs-fedorenko2016-ecog-gpt2-small-reproduce` | Fedorenko 逐词 ECoG 电极 | gpt2-small `transformer.h.11` | L，10 折，按 sentence_id 分组 |
| `alignment-bs-blank2014-fmri-distilgpt2-reproduce` | Blank 故事片段 fMRI fROI | distilgpt2 `transformer.h.5` | L，8 折，按 story 分组 |
| `alignment-bs-blank2014-fmri-gpt2-small-reproduce` | Blank 故事片段 fMRI fROI | gpt2-small `transformer.h.11` | L，8 折，按 story 分组 |
| `alignment-bs-futrell2018-reading-times-distilgpt2-reproduce` | Futrell 逐词人类阅读时间 | distilgpt2 逐词 surprisal | B，复现行为相关 |
| `alignment-bs-futrell2018-reading-times-gpt2-small-reproduce` | Futrell 逐词人类阅读时间 | gpt2-small 逐词 surprisal | B，复现行为相关 |

## 5 全部 6 个 T2 双模型比较实例

T2 提供同一来源下两个候选模型的数据。Agent 须先对每个 case 完整执行 V、L 或 B，再在相同刺激、测量单元和协议下比较；不能只读现成分数写排名。

| Task ID | 提供的数据组合 | Agent 需要回答的问题 |
|---|---|---|
| `alignment-bs-majajhong2015-compare` | V4、IT × pixels、AlexNet，共 4 个 case | 分别在 V4 和 IT 上，AlexNet 相比 pixels 的 normalized 差值是多少？物体类别和测量覆盖如何？ |
| `alignment-bs-freemanziemba2013-compare` | V1、V2 × pixels、AlexNet，共 4 个 case | 分别在 V1 和 V2 上，两种候选的分数和纹理类型描述结果有何差异？ |
| `alignment-bs-pereira2018-compare` | 243 句、384 句实验 × distilgpt2、gpt2-small，共 4 个 case | 两个实验中 gpt2-small 相比 distilgpt2 的差值分别是多少？被试和 story 覆盖如何？ |
| `alignment-bs-fedorenko2016-compare` | ECoG × distilgpt2、gpt2-small，共 2 个 case | 在相同逐词电极响应上，两种固定表示的预测分数如何比较？被试覆盖如何？ |
| `alignment-bs-blank2014-compare` | fMRI fROI × distilgpt2、gpt2-small，共 2 个 case | 在相同故事划分上，两种表示的预测分数及被试／story 描述有何差异？ |
| `alignment-bs-futrell2018-compare` | 阅读时间 × distilgpt2、gpt2-small，共 2 个 case | 在相同纳入词和被试响应上，两种模型输出的归一化相关、原始有符号相关及分组描述如何比较？ |

比较方向由 `instance.json` 固定：视觉是 **AlexNet − pixels**，语言是 **gpt2-small − distilgpt2**，比较量为 normalized 的差。每个 benchmark 分别报告差值和排名；绝对差不超过 `1e-6` 记为 `numerical_tie`。不能把不同脑区、不同实验混成一个未定义总分。

这些是给定刺激和测量单元范围内的描述性比较。交叉验证折不能充当独立研究样本，也没有通过这套流程建立因果关系或检验新被试泛化。

### 两种模板都要求的分组描述

神经任务按已记录的被试身份，先计算每折该被试有限单元相关的中位数，再平均有效折；记录有效折数，不补造未知被试身份。对存在的 `story`、`texture_type`、`object_name`，按标签汇集测试预测与响应，逐单元计算有符号相关，再取有效单元中位数。重复随机划分中，同一刺激的多次出现仍须标明不独立。

行为任务在相同句首词排除规则下，报告每名被试的有符号相关和有效词数，以及每个 story 上模型与被试均值的相关。数据不足或方差为零导致相关未定义时写 `null`。具体字段和计算细节以 [INPUT_CONTRACT.md](INPUT_CONTRACT.md) 为准。

## 6 每个 task 要提交什么

程序入口统一为：

```bash
python submission/analyze.py --inputs DIR --output DIR
```

`--output` 指向产物根目录，程序应在其中生成 `results/`、`conclusion.json` 和 `report.md`。提交时按任务工作区规定路径保存这些文件。

| 产物 | 内容 |
|---|---|
| `submission/analyze.py` 和所需辅助源码 | 能从指定输入重新计算结果的程序 |
| `results/summary.json` | 输入身份及哈希、每个 case 的 raw／ceiling／normalized／unclipped、聚合方法、分组描述；T2 还包括逐 benchmark 比较 |
| `results/trace.json` | case 与折身份、训练和测试 ID、测量单元 ID、alpha、数值数组文件名；行为任务记录词 ID、掩码文件等，`folds` 为空 |
| `results/*.npy` | 神经任务：每折测试条目 × 单元的预测矩阵及逐单元指标；行为任务：完整模型输出、响应有效掩码、纳入词掩码 |
| `conclusion.json` | 结构化结论，保留比较排名和适用范围；明确未建立因果、未测试新被试泛化、CV 折不独立、模型分数不等于 Agent 成绩 |
| `report.md` | 非空分析报告，解释方法、覆盖情况、结果及限制；负结果或无法下更强结论也应如实报告 |

JSON schema、确切字段、数组约束与数值容差见 [INPUT_CONTRACT.md](INPUT_CONTRACT.md)。T1 的 `comparisons` 为空，仍然需要数值轨迹、分组描述和报告。

## 7 怎样判断 Agent 完成了任务

主评分为二元 `analysis_success`。保存的结果、隔离重跑和输入扰动检查均通过才为 1；模型与脑或行为的对应很弱，也可以得到 1。

评分器核对逐折预测、单元指标、掩码、聚合和结论字段，不仅比较最终一个数。它会在无网络环境中重跑提交源码，并对神经任务修改第一折测试响应、对行为任务轮换纳入词的模型输出，以检查程序是否重新计算。固定答案和伪造 stdout 无法代替分析。

数据或环境缺失属于基础设施失败，不算 Agent 得 0。报告文字质量和独立 Agent 验收另行审阅；合成数据测试不能代替真实数据验证。

## 8 当前可用程度和后续入口

| 范围 | 当前状态 |
|---|---|
| 24 个实例定义、输入契约、分析与评分流程 | 已实现，全部通过合成数据流程验证 |
| Pereira384 × distilgpt2 | 已复用本机真实文件，完成官方与缓存等价验证、维护者基线及完整 CLI 评分 |
| 其余真实组合与 T2 真实比较 | 等待对应来源资产、固定权重或 ceiling；尚未完成真实数据验收 |
| 独立 Agent 成绩及正式任务准入 | 尚未完成；新增正式 canonical task 为 0 |

逐实例机器可读定义见 [instances.json](instances.json)，操作命令见 [README.md](README.md)，真实验证证据见 [VALIDATION.md](VALIDATION.md)，上游出处和来源条件见 [SOURCE_AUDIT.md](SOURCE_AUDIT.md)。维护者也可使用 README 中的 `draft` 命令导出每个实例的 `prompt.draft.md` 和 `contract.draft.json` 进行逐项审阅。
