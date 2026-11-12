# Brain-Score 官方基线与 Agent 参考结果核验

核验日期：2026-11-11。范围为 [instances.json](instances.json) 中的 18 个复现实例和 6 个比较实例。核验只读取官方源码、测试和公开网页，没有下载实验数据、刺激、模型权重，也没有重新运行真实评分。

必须区分三种证据：**官方提供可运行方法、官方公布候选模型分数、我们在冻结配置下生成逐折参考结果**。前两者可用于来源验证和外部对照，第三种才足以严格核验 Agent 的完整分析。网站四舍五入分数、其他数据子集的分数或 dummy test 数值不能直接充当逐折标准答案。

核验结果：**10 个语言复现实例均找到同名 benchmark 的官方网页成绩；8 个视觉 public 复现实例尚未确认可直接用于当前配置的公开数值；6 个比较任务是本仓库定义的 Agent 任务。** 视觉中 pixels × public IT 虽有官方教程示例，其数值与当前冻结归一化公式不一致。所有 18 个复现实例均有官方方法和候选实现，真实数据上的严格参考仍需在冻结配置下生成。

## 1 固定源码核验范围

本次读取的完整官方 checkout 为 `/tmp/bpb-bs-vision-src-20261111` 和 `/tmp/bpb-bs-language-src-20261111`，分别核对 HEAD 为下列 commit，工作树均无修改。检索覆盖相应 benchmark、候选模型注册与测试，并搜索仓库其他测试和结果文件中的候选名及 benchmark ID。

| 生态 | 固定版本 | 核验结论 |
|---|---|---|
| Vision | [`c5608668783fe654f83611305fb7e717db0a0cbf`](https://github.com/brain-score/vision/tree/c5608668783fe654f83611305fb7e717db0a0cbf) | 四个 public benchmark、pixels 和 AlexNet 均有官方实现；找到的候选模型 IT 测试分数对应 private benchmark |
| Language | [`cc9f623151b5e64be1919c8a8a8b08edc317b784`](https://github.com/brain-score/language/tree/cc9f623151b5e64be1919c8a8a8b08edc317b784) | 五个目标 benchmark、distilgpt2 和 gpt2 均有官方实现；所检索测试未包含这十个精确组合的完整候选得分 |

“未找到”限定于上述固定源码范围，不表示 Brain-Score 网站、历史论文或其他版本从未公布过得分。网站核验另见第 4 节。

### 模型身份和层是否一致

- 官方 distilgpt2 注册为 `transformer.h.5`，官方 gpt2 注册为 `transformer.h.11`，与我方固定层一致。我方 `gpt2-small` 是该小型 gpt2 的本地候选 ID，不是另一个官方模型。注册注释说明层选择参考了旧 Pereira encoding 的最高得分层，不能将其解释成完全独立于 Pereira 的新发现。[GPT 注册 L5–15](https://github.com/brain-score/language/blob/cc9f623151b5e64be1919c8a8a8b08edc317b784/brainscore_language/models/gpt/__init__.py#L5-L15)
- 官方 AlexNet 映射为 V1→`features.2`、V2/V4→`features.7`、IT→`features.12`；pixels 在四个脑区都使用 `pixels`，与我方一致。[AlexNet 映射](https://github.com/brain-score/vision/blob/c5608668783fe654f83611305fb7e717db0a0cbf/brainscore_vision/models/alexnet/region_layer_map/alexnet.json#L1)、[pixels 映射](https://github.com/brain-score/vision/blob/c5608668783fe654f83611305fb7e717db0a0cbf/brainscore_vision/models/pixels/region_layer_map/pixels.json#L1)
- 语言官方注册和默认加载调用没有固定 Hub revision；我方另行固定了模型和 tokenizer 字节。因此模型名及层相同，仍不足以证明某条历史网站成绩使用了完全相同的权重、依赖和运行环境。[官方加载 L54–80](https://github.com/brain-score/language/blob/cc9f623151b5e64be1919c8a8a8b08edc317b784/brainscore_language/model_helpers/huggingface.py#L54-L80)、[本地候选锁](candidates.json)

## 2 全部 18 个复现实例的源码基线核验

下表的“测试参考”指官方固定源码中的完整候选得分断言，不是网站得分。各行均存在官方 benchmark 和候选实现；尚无精确测试值的行仍可由官方流程生成参考结果。

| Task ID | 我方目标配置 | 官方测试参考与可比性 |
|---|---|---|
| `alignment-bs-majajhong2015-it-alexnet-reproduce` | public IT × AlexNet `features.12` | 找到 private IT 的 normalized `0.417 ± 0.001`，不可用作 public IT 标准答案。[V1] |
| `alignment-bs-majajhong2015-it-pixels-reproduce` | public IT × pixels | 找到 private IT 的 normalized `0.0126 ± 0.001`，不可用作 public IT 标准答案。[V2] |
| `alignment-bs-majajhong2015-v4-alexnet-reproduce` | public V4 × AlexNet `features.7` | 找到 private V4 预计算 `features.12` 的 raw `0.490236 ± 0.005`；数据子集、层均不同。[V3] |
| `alignment-bs-majajhong2015-v4-pixels-reproduce` | public V4 × pixels | 未找到该候选组合的完整测试得分；public V4 的 `0.897956` 是脑数据自回归 raw。[V4] |
| `alignment-bs-freemanziemba2013-v1-alexnet-reproduce` | public V1 × AlexNet `features.2` | 找到 private aperture 预计算特征的 raw `0.466222 ± 0.005`；不是 public V1 的候选参考。[V5] |
| `alignment-bs-freemanziemba2013-v1-pixels-reproduce` | public V1 × pixels | 未找到该候选组合的完整测试得分；public V1 的 `0.679954` 是脑数据自回归 raw。[V6] |
| `alignment-bs-freemanziemba2013-v2-alexnet-reproduce` | public V2 × AlexNet `features.7` | 找到 private aperture 预计算特征的 raw `0.459283 ± 0.005`；不是 public V2 的候选参考。[V5] |
| `alignment-bs-freemanziemba2013-v2-pixels-reproduce` | public V2 × pixels | 未找到该候选组合的完整测试得分；public V2 的 `0.577498` 是脑数据自回归 raw。[V6] |
| `alignment-bs-pereira2018-243sentences-distilgpt2-reproduce` | 243 sentences ridge × distilgpt2 `h.5` | 未找到精确组合测试值；benchmark 测试使用 linear-shuffle 与 DummyModel。[L1][L4] |
| `alignment-bs-pereira2018-243sentences-gpt2-small-reproduce` | 243 sentences ridge × gpt2 `h.11` | 未找到精确组合测试值；同上。[L1][L4] |
| `alignment-bs-pereira2018-384sentences-distilgpt2-reproduce` | 384 sentences ridge × distilgpt2 `h.5` | 未找到精确组合测试值；本地另有真实官方/cache 等价参考 `0.5831730146921874`，见第 6 节。[L1][L4] |
| `alignment-bs-pereira2018-384sentences-gpt2-small-reproduce` | 384 sentences ridge × gpt2 `h.11` | 未找到精确组合测试值；benchmark 测试使用 linear-shuffle 与 DummyModel。[L1][L4] |
| `alignment-bs-fedorenko2016-ecog-distilgpt2-reproduce` | Fedorenko ridge × distilgpt2 `h.5` | 未找到精确组合测试值；该 benchmark 目录没有 test.py，注册与实现存在。[L3][L4] |
| `alignment-bs-fedorenko2016-ecog-gpt2-small-reproduce` | Fedorenko ridge × gpt2 `h.11` | 未找到精确组合测试值；同上。[L3][L4] |
| `alignment-bs-blank2014-fmri-distilgpt2-reproduce` | Blank ridge × distilgpt2 `h.5` | 未找到精确组合测试值；benchmark 测试使用 linear-shuffle 与 DummyModel。[L2][L4] |
| `alignment-bs-blank2014-fmri-gpt2-small-reproduce` | Blank ridge × gpt2 `h.11` | 未找到精确组合测试值；同上。[L2][L4] |
| `alignment-bs-futrell2018-reading-times-distilgpt2-reproduce` | Futrell Pearson × distilgpt2 surprisal | 未找到完整候选得分；官方有随机／自预测测试及 distilgpt2 八词输出测试，README 给出此组合运行命令。[L5][L4][L6] |
| `alignment-bs-futrell2018-reading-times-gpt2-small-reproduce` | Futrell Pearson × gpt2 surprisal | 未找到完整候选得分；官方有随机／自预测测试及 gpt2 八词输出测试。[L5][L4] |

[V1]: https://github.com/brain-score/vision/blob/c5608668783fe654f83611305fb7e717db0a0cbf/brainscore_vision/models/alexnet/test.py#L7-L15
[V2]: https://github.com/brain-score/vision/blob/c5608668783fe654f83611305fb7e717db0a0cbf/brainscore_vision/models/pixels/test.py#L7-L15
[V3]: https://github.com/brain-score/vision/blob/c5608668783fe654f83611305fb7e717db0a0cbf/brainscore_vision/benchmarks/majajhong2015/test.py#L47-L58
[V4]: https://github.com/brain-score/vision/blob/c5608668783fe654f83611305fb7e717db0a0cbf/brainscore_vision/benchmarks/majajhong2015/test.py#L92-L103
[V5]: https://github.com/brain-score/vision/blob/c5608668783fe654f83611305fb7e717db0a0cbf/brainscore_vision/benchmarks/freemanziemba2013/test.py#L44-L54
[V6]: https://github.com/brain-score/vision/blob/c5608668783fe654f83611305fb7e717db0a0cbf/brainscore_vision/benchmarks/freemanziemba2013/test.py#L88-L98
[L1]: https://github.com/brain-score/language/blob/cc9f623151b5e64be1919c8a8a8b08edc317b784/brainscore_language/benchmarks/pereira2018/test.py#L26-L80
[L2]: https://github.com/brain-score/language/blob/cc9f623151b5e64be1919c8a8a8b08edc317b784/brainscore_language/benchmarks/blank2014/test.py#L25-L68
[L3]: https://github.com/brain-score/language/tree/cc9f623151b5e64be1919c8a8a8b08edc317b784/brainscore_language/benchmarks/fedorenko2016
[L4]: https://github.com/brain-score/language/blob/cc9f623151b5e64be1919c8a8a8b08edc317b784/brainscore_language/models/gpt/test.py#L8-L77
[L5]: https://github.com/brain-score/language/blob/cc9f623151b5e64be1919c8a8a8b08edc317b784/brainscore_language/benchmarks/futrell2018/test.py#L25-L43
[L6]: https://github.com/brain-score/language/blob/cc9f623151b5e64be1919c8a8a8b08edc317b784/README.md#L34-L40

## 3 为什么找到数值仍不能直接套用

**视觉 public 与 private 是不同注册和不同数据。** MajajHong 的 private IT 构造器明确使用 `access='private'`，public IT 明确使用 `access='public'`。Freeman public 模块也明确说明 public 供本地原型和层选择，最终网站评测使用留出的 private 数据。因此同一模型在 private 上的分数不能验收 public 分析。[Majaj 构造 L47–62](https://github.com/brain-score/vision/blob/c5608668783fe654f83611305fb7e717db0a0cbf/brainscore_vision/benchmarks/majajhong2015/benchmark.py#L47-L62)、[Freeman public 说明 L1–7](https://github.com/brain-score/vision/blob/c5608668783fe654f83611305fb7e717db0a0cbf/brainscore_vision/benchmarks/freemanziemba2013/benchmarks/public_benchmarks.py#L1-L7)

**预计算特征测试返回 raw，模型端到端测试返回最终分数。** Majaj private 预计算 AlexNet `features.12` 测试的 V4/IT 数值分别为 `0.490236/0.584053`，Freeman private 预计算测试的 V1/V2 数值为 `0.466222/0.459283`，容差均为 `abs=0.005`；测试 helper 明确取 `.raw`。这些数不能与 AlexNet 模型测试的 normalized `0.417` 直接比较。[预计算 helper L88–91](https://github.com/brain-score/vision/blob/c5608668783fe654f83611305fb7e717db0a0cbf/brainscore_vision/benchmark_helpers/test_helper.py#L88-L91)、[Majaj 测试][V3]、[Freeman 测试][V5]

**public 自回归测试不是模型基线。** Majaj public V4/IT 的 `0.897956/0.816251`、Freeman public V1/V2 的 `0.679954/0.577498`，均把实验 assembly 本身作为 source 后取 raw，容差 `abs=0.001`。它们验证 benchmark 运算，不能当成 pixels/AlexNet 得分。[Majaj 自回归][V4]、[Freeman 自回归][V6]

**语言 legacy linear-shuffle 与本轮 ridge 不能混用。** Pereira 和 Blank 同时注册两套方法；现有 benchmark 测试的随机模型、exact model 和 ceiling 数值仍显式加载 `linear-shuffle`。Pereira 测试 ceiling `0.35378928/0.36343748` 不是本轮 ridge ceiling；不能因此把本地 Pereira384 ridge ceiling `0.13521249808656496` 判错。[Pereira 注册](https://github.com/brain-score/language/blob/cc9f623151b5e64be1919c8a8a8b08edc317b784/brainscore_language/benchmarks/pereira2018/__init__.py#L1-L9)、[Pereira 测试][L1]、[Blank 注册](https://github.com/brain-score/language/blob/cc9f623151b5e64be1919c8a8a8b08edc317b784/brainscore_language/benchmarks/blank2014/__init__.py#L1-L5)

**模型单元测试不是数据集成绩。** GPT 测试在八个示例词上核对 surprisal（`atol=0.0001`），并检查简单文本的 next-word 输出和 768 维神经表示形状；Futrell benchmark 测试使用随机输出或实验均值，ceiling 断言约为 `0.858`。这些是有用的软件检查，但没有给出 distilgpt2/gpt2 在全部 Futrell 数据上的候选分数。[GPT 测试][L4]、[Futrell 测试][L5]

## 4 官方网站公布成绩核验

本节核对官方模型详情页和教程，并于 2026-11-11 直接读取这五个网页的 HTML 复查分数；没有访问刺激图片或数据集对象。网页分数观察、18 个实例的对应关系与所读 HTML 的 SHA256 记在 [published-baseline-observations.json](evidence/20261111/published-baseline-observations.json)。网页会更新，哈希绑定的是本次读取内容，不表示网站承诺长期固定该版本。

### 十个语言组合都有公布分数

以下是网页显示的归一化分数，均保留页面的三位小数精度。官方模型名为 `gpt2`，对应我们清单中的 `gpt2-small`。两候选在五个目标 benchmark 上都不是空缺，故覆盖本轮全部 10 个语言 T1 实例。来源为 [distilgpt2 模型页](https://www.brain-score.org/model/language/1651)和 [gpt2 模型页](https://www.brain-score.org/model/language/2072)；Futrell 还可在[该 benchmark 榜单](https://www.brain-score.org/benchmark/language/132)交叉核对。

| 官方 benchmark | 版本 | distilgpt2 | gpt2 | 由显示值计算的 gpt2−distilgpt2 |
|---|---:|---:|---:|---:|
| `Pereira2018.243sentences-ridge` | 1 | 0.821 | 0.835 | +0.014 |
| `Pereira2018.384sentences-ridge` | 1 | 0.583 | 0.656 | +0.073 |
| `Blank2014-ridge` | 1 | 0.176 | 0.121 | −0.055 |
| `Fedorenko2016-ridge` | 3 | 0.476 | 0.413 | −0.063 |
| `Futrell2018-pearsonr` | 1 | 0.361 | 0.367 | +0.006 |

表中差值是本次根据网页显示值计算的近似值，不是官方发布的 T2 Agent 基线。它们为四个语言 T2 实例提供了外部数值和方向参考，但没有覆盖本仓库要求的逐折预测、被试／刺激分组和输入扰动检查。

我方 Pereira384 × distilgpt2 实测 `0.5831730146921874` 四舍五入为 `0.583`，与官网显示精度一致。其他九个语言组合尚未在本轮全部真实运行，不能据此声称已数值复现。两个语言模型页均显示未记录 layer commitment；固定源码的层映射虽与我们一致，网站记录仍没有提供足以逐项确认历史提交权重、模型 revision、依赖和源码身份的证据。因此这些网页值用于外部对照，不用于 `1e-6/1e-5` 级别的严格评分。[本地实测证据](VALIDATION.md)、[distilgpt2 页面](https://www.brain-score.org/model/language/1651)、[gpt2 页面](https://www.brain-score.org/model/language/2072)

### 八个视觉 public 组合不能直接采用普通榜单成绩

[AlexNet 模型页](https://www.brain-score.org/model/vision/982)和 [pixels 模型页](https://www.brain-score.org/model/vision/678)确实公布了下列成绩，但它们的 benchmark ID **不含 `public`**。这与我方八个视觉任务的数据子集不同；Freeman 还存在 private v3 与 public v1 的版本差别。

| 网页 benchmark | 网页版本 | AlexNet | pixels | 与我方配置的关系 |
|---|---:|---:|---:|---|
| `MajajHong2015.V4-pls` | 4 | 0.492 | 0.061 | 我方是 `MajajHong2015public.V4-pls`，不能直接对分 |
| `MajajHong2015.IT-pls` | 4 | 0.417 | 0.013 | 我方是 `MajajHong2015public.IT-pls`，不能直接对分 |
| `FreemanZiemba2013.V1-pls` | 3 | 0.276 | 0.047 | 我方是 public v1，不能直接对分 |
| `FreemanZiemba2013.V2-pls` | 3 | 0.291 | 0.003 | 我方是 public v1，不能直接对分 |

AlexNet 页面公布的 V1/V2/V4/IT 层映射与我方一致，但这不能消除数据子集差异。页面另有 `MajajHong2015public.*-reverse_pls` 成绩，指标是 reverse PLS，同样不能用于我方正向 PLS 任务。本次检查的模型页和固定源码测试未提供这八个精确 public 配置的可直接验收分数；这不等于证明所有历史材料中都没有。

### 官方教程中确实有一个 public 示例，但不能直接用作当前答案

[Quickstart](https://www.brain-score.org/tutorials/models/quickstart)明确演示 `pixels × MajajHong2015public.IT-pls`，并列出 score `0.07637264`、raw `0.22545106`、ceiling `0.81579938`。这证明该组合是官方演示的使用路径。

不过，按本轮冻结源码的 `raw² / ceiling` 公式代入，得到约 **0.06230475**；教程 score 则与 `(raw / ceiling)²` 的约 **0.07637264** 一致。这里仅核算示例数字，没有重新跑实验，也不把 0.06230475 当作当前真实模型分数。教程未给出足够版本绑定，不能确定差异是历史公式还是示例未更新，因此这条示例不纳入严格金标准。[冻结归一化源码 L315–324](https://github.com/brain-score/vision/blob/c5608668783fe654f83611305fb7e717db0a0cbf/brainscore_vision/benchmark_helpers/neural_common.py#L315-L324)

## 5 六个比较任务的来源

以下 task ID 由本仓库定义。固定上游注册的是各个科学 benchmark 与候选模型，没有找到这六个 Agent 比较任务的对应注册、提交契约或 `analysis_success` 基线。它们的参考结果应由同一来源内各个官方评分结果及本仓库规定的差值、排名和分组描述组成。[本地实例定义](instances.json)、[比较契约](INPUT_CONTRACT.md)

| Task ID | 参考构成 |
|---|---|
| `alignment-bs-majajhong2015-compare` | 两个 public 脑区 × pixels/AlexNet，分别计算候选分数和 AlexNet−pixels |
| `alignment-bs-freemanziemba2013-compare` | 两个 public 脑区 × pixels/AlexNet，分别计算候选分数和 AlexNet−pixels |
| `alignment-bs-pereira2018-compare` | 两个 ridge 实验 × distilgpt2/gpt2，分别计算候选分数和 gpt2−distilgpt2 |
| `alignment-bs-fedorenko2016-compare` | ridge × distilgpt2/gpt2，计算候选分数和 gpt2−distilgpt2 |
| `alignment-bs-blank2014-compare` | ridge × distilgpt2/gpt2，计算候选分数和 gpt2−distilgpt2 |
| `alignment-bs-futrell2018-compare` | Pearson × distilgpt2/gpt2，计算候选分数和 gpt2−distilgpt2 |

两条网站成绩可以提供描述性差值的外部参照，但不能代替两候选使用完全相同刺激、响应、划分、排除规则和版本的验证。网站四舍五入也不足以判定本仓库 `1e-6` 的 numerical tie 条件。

Brain-Score 网站也有通用的 [Compare 功能](https://www.brain-score.org/language/compare/)，可展示两个模型共享 benchmark 的分数和差值。这支持模型比较这一用途，但该网页工具没有构成本仓库六个 Agent task 的代码提交、逐折轨迹、分组描述和 `analysis_success` 验收协议。

## 6 当前可以如何对比 Agent

本地已有 **Pereira384 × distilgpt2** 真实参考：raw `0.07885228013320371`、ceiling `0.13521249808656496`、normalized `0.5831730146921874`。官方原始调用与缓存分析的分数、10 折预测、逐单元指标和 alpha 均已核对；维护者基线通过隔离评分，但还不是独立 Agent 成绩。[验证记录](VALIDATION.md)

其余精确组合已经有官方方法绑定、参考程序和合成检查，但尚未全部建立真实输入下的逐折参考结果。任务正式验收应使用同一冻结输入的参考运行：先核对官方流程与缓存等价，再比较 Agent 数值轨迹、结构化结论、隔离重跑和输入扰动结果。公布的模型分数用于外部合理性检查，Agent 的 `analysis_success` 用于衡量分析正确性，两者分别记录。
