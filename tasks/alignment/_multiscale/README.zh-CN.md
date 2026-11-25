# 词序敏感单元与人脑响应

2026-11-19，首轮真实 CPU 实验。克隆仓库后，用浏览器打开五步回放，即可查看独立 Agent 和固定 top-k 的两次运行。页面可单独复制，离线使用。[五步回放](evidence/20261119/replay/demo.html)

归档保留了每一步的工具请求与返回、两次冻结的映射及逐句预测，以及对应的 SHA-256 校验清单。[工具记录](evidence/20261119/replay/events.json) · [Agent 的冻结提交](evidence/20261119/replay/agent-frozen.json) · [固定 top-k 的提交](evidence/20261119/replay/baseline-frozen.json) · [校验清单](evidence/20261119/replay/sha256.json)

单细胞、模型回路、区域网络和全系统另有四张可独立评分的实验卡，均已用真实数据完成维护者固定参考运行。[四层任务、结果与运行命令](LEVELS.zh-CN.md) · [可解释性方法与原始文献](METHODS.zh-CN.md)

## 首轮结果

独立 Codex 研究 Agent 先检查第 5 层的一组单元。开发集上的词序效应为 +0.701 个训练标准差，脑预测增量为 +0.003。第二次它选了第 2 层的 8 个单元，开发集词序效应降到 +0.271，脑预测增量升到 +0.051。它冻结了第二组，在确认材料上选择将中间词循环左移一位，以保留多数中间词的邻接关系。

32 个独立句对中有 28 对的激活差符合 Agent 的正向预测，平均原句减扰动句为 **+0.345 个训练标准差**。候选组相对匹配随机组的额外消融损失，在两种词序间相差 **−0.0080 nat**，落在事前指定的 ±0.01 nat 区间。固定 top-k 选择第 5 层并反转中间词，测得 +0.760 个标准差与 +0.0673 nat。两次运行选择了不同的确认扰动。

下表每个数都是同一参与者、同一批句子上，加入单元后的 Pearson 相关减去仅用控制变量的相关。增强和抑制标签只在评分端读取。原研究特意挑选了这两个条件的刺激。[Tuckute 等的原研究](https://www.nature.com/articles/s41562-023-01783-7)

| 参与者 | Agent 全部 500 句 | 固定 top-k 全部 | 匹配随机组均值¹ | 固定整层¹ | Agent 增强组内 250 句 | Agent 抑制组内 250 句 |
|---|---:|---:|---:|---:|---:|---:|
| 797 | +0.0440 | +0.0137 | +0.0217 | +0.0866 | +0.0048 | +0.0031 |
| 841 | +0.0406 | −0.0062 | +0.0170 | +0.0963 | +0.0164 | −0.0211 |
| 880 | +0.0310 | +0.0055 | +0.0119 | +0.1047 | +0.0076 | −0.0246 |

¹ 全部 500 句。随机组与 Agent 选定的单元匹配。整层参照使用句末 token 最后归一化的隐藏状态。回放可切换两种策略和三个条件，查看完整比较。

Agent 预估每位留出参与者的总体增量在 [−0.015, +0.100]，三人的观测值均落在区间内。两位参与者在抑制条件内的增益为负。解释的适用范围是这次短句扰动和这三位参与者的左半球语言网络平均响应。单次独立运行记录了研究决策，比较 Agent 间稳定表现仍需更多运行。

## 数据、单元与预算

- 从锁定的 Tuckute CSV 复用任务 F 的筛选。训练为 988 句、5 人，留出为另外 500 句、3 人。源文件和全部脑响应保存在运行包之外的维护者目录。输入审计保留真实呈现的参与者、session、run、trial 和对应 token。数据源已公开，运行内隐藏响应不能排除模型预训练时接触过来源。[F 的验收记录](../EXPANSION_VALIDATION.md#f)
- 训练句按稳定 ID 排列成固定分区。720 句用于搜索，144 句用于开发，124 句预留给独立模型确认。每个原句及其所有改写属于同一分区。搜索、开发、确认各取 96、32、32 对可比句。探测句对限制为标点可对齐、末词恰为一个 token 的材料，逐对核验首末词、词集合、token 集合、目标索引和后缀。脑预测仍使用全部 500 个实测原句。
- 模型与 tokenizer 均为 distilgpt2 的 `2290a62682d06624634c1f46a6ad5be0f47f38aa`。查询范围是 6 层、每层 3072 个原生 MLP 单元，以及目标词前 1 或 2 个 token。读出取 GELU 后、MLP 输出投影之前。词序差先按各单元在 720 个原句上的标准差缩放，再在 8 个单元上取均值。
- 两种策略获得同一次全量搜索摘要和两次 8 单元组查询，每次可看到两组开发指标及高低激活样例。Agent 自选层、位置、ID 和确认扰动。固定策略检查按搜索词序差排序的前两个层与位置组合，冻结第一名的 8 个单元。固定参考使用提前规定的反转扰动。
- 冻结时登记两条激活假设、每个确认句对的预测、消融交互方向及总体脑增益区间，并保存全部岭回归映射和逐句预测。激活近零阈值为 ±0.05 个训练标准差，消融交互近零阈值为 ±0.01 nat。干预只给模型目标词前的前缀，在所选位置将 8 个激活置零。随机组在同层同位置按搜索集激活均方根匹配，各抽 8 个单元，共 8 组。
- 脑预测使用搜索与开发合计 864 句的训练参与者平均响应。每次读出均用训练集标准化、固定岭参数 100 和截距。控制变量为词数、token 数和句内平均下一 token surprisal（自然对数，跳过无前文的首 token）。评分端从冻结的单元和训练材料重建所有映射、核对 500 句预测后，才读取留出响应。常数序列的相关记为未定义。

本次独立 Agent 使用全新上下文。操作者向它转发公开的搜索摘要、两次查询反馈和冻结后的观测，并按其原文登记选择和最终判断。G 的输入核验由准备程序执行。这是 H/I 联动的服务器实验，工作区级盲测和单独评分的 G、H、I 任务卡仍是后续工作。

## 开放探索试点的题面与主指标

下面是下一轮独立评测的题面草案。

> 给你训练句子的 distilgpt2 单元激活和人类左半球语言网络 fMRI 响应。请找出 8 个模型单元，使它们在未见句子上尽可能提高对新参与者逐句脑响应的预测。你可以写代码分析训练材料，自选模型层、读取位置和单元组合，最多向开发集查询两组单元的表现。最后提交一组单元及可重跑的选择代码。评分端冻结选择，再用留出测量评分。

**主指标**取同一刺激条件内的预测增益。对于每位留出参与者，分别在增强句和抑制句内计算两个 Pearson 相关。第一个是「控制变量加所选单元」的预测与实测脑响应的相关，第二个是仅用控制变量的预测与同一批实测响应的相关。前者减去后者得到 Δr。主分取 `(各参与者增强句 Δr 的均值 + 各参与者抑制句 Δr 的均值) / 2`，越高越好，保留负值。这样可以检验策略在同一类句子里能否预测哪一句引起更强的响应。评测前须核验每格实测值与控制预测均有方差。若提交的预测在某格恒定，则整份提交的主分记为未定义。[逐人逐条件的计算](../_shared/multiscale/analysis.py)

为比较单元选择能力，所有策略用同一冻结模型，在同一层、同一读取位置提交 8 个不同的原生 MLP 单元。评分器统一用训练数据拟合读出，控制词数、token 数和平均 surprisal。试点拟提供逐句训练激活，让 Agent 自行决定检查哪些现象、如何生成候选、看过开发反馈后是否修改选择。开发反馈用与盲评分开的参与者和句子，两处都包含增强和抑制材料。最终评分只接受一次冻结提交。实验记录用于解释决策，排名只用主指标。

### 用已有冻结提交校准题目

2026-11-23 在历史包的 500 句、3 位参与者上复算。两种历史策略沿用各自的冻结预测。另加一条固定搜索规则作参照。它读取与历史 Agent 相同的训练摘要，按每组 8 个单元与训练脑响应的平均绝对相关选出前两个层与位置组合，查询两次开发增益，冻结较高的一组。两组都在第 0 层，目标词前一个和前两个 token 的开发增益分别为 +0.10757 和 +0.04508，固定规则选了前者。这里的开发反馈沿用旧实验的基线句增益。[训练摘要与开发指标](../_shared/multiscale/analysis.py) · [原始决策与预测](evidence/20261119/replay)

| 冻结策略 | 500 句合并 Δr | 增强句内 Δr | 抑制句内 Δr | 拟定主指标 |
|---|---:|---:|---:|---:|
| 历史 Agent | +0.03851 | +0.00960 | −0.01420 | −0.00230 |
| 历史固定策略，按词序效应选单元 | +0.00432 | −0.00348 | −0.00767 | −0.00558 |
| 固定搜索，按训练脑响应相关提名，再用开发反馈选组 | +0.05287 | +0.05327 | +0.01199 | +0.03263 |

历史 Agent 当时还承担词序解释和消融预测，这张表用于校准指标。要测自适应探索的贡献，可让同一底模在相同数据、算力、token 和查询预算下各跑两种设置。一种在获得开发反馈前锁定两个查询及最终选择规则，另一种可看第一次反馈再决定下一次查什么。在多个新的留出批次上，对两种设置的主指标作配对比较，并列报告固定搜索的成绩。这样能把“选出的单元有多好”和“看反馈再做决定带来多少收益”分别量出来。

## 运行与复核

命令从仓库根目录执行。本次使用 Python 3.12、NumPy 2.4.0、pandas 2.2.3、PyTorch 2.9.1、Transformers 4.57.3。模型从本地目录按仓库的固定文件指纹读取。数据与模型只在维护者侧准备。[模型文件清单](../brainscore/evidence/20261111/pereira384-model-manifest.json)

```bash
ALIGN_PYTHON=/path/to/python
ALIGN_MODEL=/path/to/local/distilgpt2
ALIGN_RAW=/tmp/multiscale-inputs
ALIGN_ROOT=/tmp/multiscale-experiment
ALIGN_CLI=tasks/alignment/_shared/multiscale_cli.py

"$ALIGN_PYTHON" -B tasks/alignment/_shared/expansion_cli.py download --task F --raw "$ALIGN_RAW"
"$ALIGN_PYTHON" -B "$ALIGN_CLI" prepare --root "$ALIGN_ROOT" --model-dir "$ALIGN_MODEL" \
  --csv "$ALIGN_RAW/f-brain-lang-data_participant_20230728.csv"
"$ALIGN_PYTHON" -B "$ALIGN_CLI" top-k --until freeze --root "$ALIGN_ROOT" --model-dir "$ALIGN_MODEL"
```

若已有 F 的公开包和隐藏包，可为 `prepare` 同时添加 `--f-inputs` 和 `--f-hidden`，核对句子、参与者、响应和包身份。新任务还需源表里的组别和呈现记录。原实验不依赖 Pereira 或其他数据集。

维护者为研究 Agent 分配固定的 `--actor`，保管 `--root` 和其中的 SQLite 日志，只通过下表接口返回本阶段工具结果。工具在每一阶段先持久化再返回，允许相同请求重试，并拒绝更改已冻结的请求。两种策略在各自冻结后才可揭晓。

| `call` 阶段 | 输入和输出 |
|---|---|
| `open` | 返回 G 的呈现审计、完整搜索摘要和预算 |
| `inspect1`、`inspect2` | 请求 JSON 含 `layer`、`position`（`pre1`／`pre2`）、8 个 `units` 和 `reason` |
| `freeze` | 提交已查询组、`reason`、`contrast`（`reverse`／`rotate`）、两条含 `explanation` 和不同 `activation` 方向的 `hypotheses`、`expected_interaction`、`expected_delta_r`。方向为 `up`、`flat`、`down` |
| `probe` | 提供 `--model-dir`，返回 32 对事前登记材料的激活及消融结果 |
| `score` | 重算并核对映射与预测，揭晓总体和两个条件的逐人结果 |
| `conclude` | 提交 `hypothesis`（`first`／`second`／`neither`）、`interaction`、`positive_participants` 和中文 `conclusion`。工具核对前三项事实，保存自由文本 |

```bash
"$ALIGN_PYTHON" -B "$ALIGN_CLI" call open --root "$ALIGN_ROOT" --actor researcher
"$ALIGN_PYTHON" -B "$ALIGN_CLI" call inspect1 --root "$ALIGN_ROOT" --actor researcher --request inspect1.json
# 按表中顺序调用其余研究阶段，JSON 由实际参与者给出。
"$ALIGN_PYTHON" -B "$ALIGN_CLI" top-k --root "$ALIGN_ROOT" --model-dir "$ALIGN_MODEL"
"$ALIGN_PYTHON" -B "$ALIGN_CLI" export --root "$ALIGN_ROOT" --actor researcher --out runs/my-multiscale-replay
"$ALIGN_PYTHON" -B "$ALIGN_CLI" replay --root "$ALIGN_ROOT" --model-dir "$ALIGN_MODEL" --bundle runs/my-multiscale-replay
```

`replay` 可以在用相同数据和环境重新准备的目录里运行。它读取导出包中的原始决策，重新执行两种策略的七个阶段，核对每个工具返回、映射和预测。复算固定决策不会产生新的独立 Agent 成绩。可另外运行 `"$ALIGN_PYTHON" -B tasks/alignment/_shared/test_multiscale.py` 检查读出、条件内计分、冻结顺序和干预位置。

本次运行的输入包 SHA-256 为 `5ba136a95d54d9db8ac0983f387c7cf0036af09a7534a115492a1f4f071ca706`。在相同输入上重算旧 F 的固定策略，三位参与者的平均响应差仍为 0.3473532235602182。[旧 F 参考结果](../EXPANSION_VALIDATION.md#f)

在新检出的仓库中，准备好 `ALIGN_ROOT` 后可直接从归档的原始决策重建本次演示。下列命令按原时间戳逐步重算两条轨迹，核对每步摘要，导出可离线打开的 `demo.html`、事件和冻结预测。[独立 Agent 与固定参考的决策和回执](evidence/demo-decisions-20261119.json)

```bash
"$ALIGN_PYTHON" -B "$ALIGN_CLI" restore --root "$ALIGN_ROOT" --model-dir "$ALIGN_MODEL" \
  --record tasks/alignment/_multiscale/evidence/demo-decisions-20261119.json --out runs/restored-multiscale
```
