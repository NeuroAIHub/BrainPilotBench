# 脑–模型对齐的四个拓展任务

第 1、3、4、5 层各有一张可独立运行的实验任务卡。第 2 层沿用现有群体表征任务。下表是固定参考策略在真实留出数据上的结果。它每次选择开发值最大的候选，用开发值预测留出值，在揭晓前冻结。独立研究 Agent 的运行记录见同项目的词序实验。[第 2 层已有任务](../TASKS_A_F_GUIDE.zh-CN.md) · [词序实验与回放](README.zh-CN.md) · [四层方法与原始论文](METHODS.zh-CN.md)

开放探索版允许 Agent 自行选择组件、查询开发分并提交可重放的策略。L1 可为固定的多细胞面板自由选单元，L3 可选择上游头及任意下游层的 8 个单元，并在训练句上做精确干预。[L1 任务](../alignment-l1-cell-tuning/README.md) · [L3 任务](../alignment-l3-circuit-paths/README.md) · [L4 任务](../alignment-l4-network-edges/README.md)

| 层级 | Agent 要做的选择 | 冻结的参考选择 | 开发预测 | 留出实测 |
|---|---|---|---:|---:|
| 1 · 单个神经元 | 看高低激活词和九类语义调谐曲线，选一个与人类单细胞对应的模型单元 | distilgpt2 的 L0-U2469 | +0.9774 | **−0.2552**，同层随机单元平均 +0.0484 |
| 3 · 模型回路 | 选一个注意力头，预测只修复它通向八个 MLP 单元的连接会恢复多少目标词概率 | L1 头 8 → L2 MLP | +0.00142 nat | **+0.00049 nat**，在预设近零区间内 |
| 4 · 区域网络 | 为五个语言区选一套模型单元组，预测增强与抑制条件之间十条共变边的变化 | L4，目标词前一个 token | +0.1604 | **+0.1552**，两位留出参与者分别为 +0.2479、+0.0625 |
| 5 · 全系统 | 选一种全脑网络指标，预测谁在辣椒素条件下更想避开这种体验 | 九系统的全部连接块加全脑均值 | +0.3397 | **−0.0177**，只用全脑均值为 +0.3614 |

L0–L5 指 distilgpt2 从零开始计数的模型层。前三张卡共用仓库的这套权重。第 5 层复用 ToPS 的公开脑连接数据，用可解释的全脑图模型读出行为。每张卡单独报告有符号的科学效应、预测的绝对误差和方向命中。方向分为正、近零、负，相关的近零区间为 ±0.05，回路效应为 ±0.001 nat。本轮固定策略仅在第 4 层命中方向。自由文本保留供人复核，自动评分依据数值预测。[可核验的分数、对照与数据包指纹](evidence/levels-reference-20261119.json)

## 每张卡如何检验解释

**第 1 层 · 单细胞语义调谐。** 从 Jamali 的听句实验预先选定细胞 1。按人类试次分成 82／42 个试次，分别有 481／237 次有效词响应。模型侧按作者的九个语义域划分 476／243 个词，在载句 `I heard {word} today.` 中读取探测词的最后一个 token。每层提供开发调谐相关最高的两个单元，共 12 个候选。留出分数是九个域平均值的 Pearson 相关。这次同一人类细胞的开发和确认曲线之间仅有 +0.0692 的相关，模型单元自身为 +0.8088。九个类别上的高开发相关没有在这次换词、换试次后复现。两侧按语义域对应，各自保留原有的听句和书面载句条件。[Jamali 单细胞数据](https://figshare.com/articles/dataset/Semantic_encoding_during_language_comprehension_at_single_cell_resolution/26046127) · [Bills 等的激活解释方法](https://openaipublic.blob.core.windows.net/neuron-explainer/paper/index.html) · [开发卡](evidence/20261119/levels/alignment-single-cell-tuning/challenge.json)

**第 3 层 · 注意力头到 MLP 的直接路径。** 在任务 F 的句子中反转中间词，保留末词和 token 位置。用搜索材料定位 L2 的八个接收单元，给出上游 L1 的 12 个头。每条路径开发、确认各用 32 对不同句子。仅把选定头对八个接收单元的贡献换成原句的值，再让这八个单元的输出变化流向目标词。确认时头 8 平均恢复 +0.00029 nat，其余 11 个头平均 −0.00020 nat。作为尺度参照，完整原句与乱序句的差距为 +5.00538 nat。结果只涉及该模型的一条指定连接。[路径替换方法](https://arxiv.org/abs/2304.05969) · [开发卡](evidence/20261119/levels/alignment-head-mlp-path/challenge.json)

**第 4 层 · 五个语言区的共变。** 复用 Tuckute 的左侧额下回眶部、额下回、额中回、前颞与后颞五个区。用五位训练参与者和 720 个基线句，为每区分配八个不重复的模型单元。每个区与另外四区的逐句共变给出共十条无向边。在参与者、扫描 session、run 和条件内去均值，再逐人比较增强相对抑制的十个边变化。开发用 797 的 125 增强句和 125 抑制句，确认用另外 250 句以及参与者 841、880。固定打乱模型组与脑区对应后，两位的相关分别为 −0.0149 和 +0.1543。第二位在打乱对应后反而更高。这里的共变可包含相同刺激引起的共同响应。[Rissman 等的逐试次共变方法](https://doi.org/10.1016/j.neuroimage.2004.06.035) · [Tuckute 的刺激与测量](https://pubmed.ncbi.nlm.nih.gov/38172630/) · [开发卡](evidence/20261119/levels/alignment-language-network-edges/challenge.json)

**第 5 层 · 全脑组织与回避意愿。** ToPS Study 3 有 48 位参与者，每人每个条件五个时间窗。把 279 区的 38,781 条连接组织成九个系统，候选为全脑均值、系统分离度、在九系统图上走两步后返回起点的概率、全部 45 个系统连接块。后三者均包含全脑均值。用 28 人拟合固定岭回归、8 人开发、12 人确认，同一人的全部时间窗归入同一分区。确认分数比较每人在 CAPS 相对 REST 的五窗平均回避评分差。固定参考的连接块模型接近零，打乱脑区的系统归属后为 −0.1472，两步返回读出为 +0.3471。这里的模型从人脑实测连接计算全局状态，能检验这些状态指标与行为的关系。独立人工系统在相同条件下会否形成相似的全局组织，仍是另一个实验问题。[ToPS 研究与评分定义](https://cocoanlab.github.io/pdfs/LeeJJ2021.pdf) · [系统分离度方法](https://pmc.ncbi.nlm.nih.gov/articles/PMC4246293/) · [开发卡](evidence/20261119/levels/alignment-global-system-state/challenge.json)

## 准备与运行

从仓库根目录执行。首次使用 CLI 时，运行 `npm ci` 和 `npm run build`。语言实验已用 Python 3.12、NumPy 2.4.0、pandas 2.2.3、SciPy 1.16.3、PyTorch 2.9.1、Transformers 4.57.3 在 CPU 上验证。第 1 层只需 Jamali 的两份公开文件和本地模型。第 3、4 层沿用词序实验的准备结果，第 5 层需要 ToPS Study 3、图谱与示例参与者的公开文件。[语言输入和权重准备](README.zh-CN.md#运行与复核) · [ToPS 公开数据准备](../../mri/tops-fmri/README.md#quick-start-agent-user)

```bash
ALIGN_PYTHON=/path/to/python
ALIGN_MODEL=/path/to/local/distilgpt2
ALIGN_ROOT=/tmp/multiscale-experiment
ALIGN_CSV=/tmp/multiscale-inputs/f-brain-lang-data_participant_20230728.csv
ALIGN_TOPS=/path/to/public_data
LEVEL_ROOT=/tmp/alignment-levels
LEVEL_CLI=tasks/alignment/_shared/multiscale_levels_cli.py

"$ALIGN_PYTHON" -B "$LEVEL_CLI" fetch-unit --jamali-dir "$LEVEL_ROOT/jamali"
"$ALIGN_PYTHON" -B "$LEVEL_CLI" prepare --level 1 --root "$LEVEL_ROOT/level1" \
  --jamali-dir "$LEVEL_ROOT/jamali" --model-dir "$ALIGN_MODEL"
"$ALIGN_PYTHON" -B "$LEVEL_CLI" prepare --level 3 --root "$LEVEL_ROOT/level3" \
  --language-root "$ALIGN_ROOT" --model-dir "$ALIGN_MODEL"
"$ALIGN_PYTHON" -B "$LEVEL_CLI" prepare --level 4 --root "$LEVEL_ROOT/level4" \
  --language-root "$ALIGN_ROOT" --csv "$ALIGN_CSV"
"$ALIGN_PYTHON" -B "$LEVEL_CLI" prepare --level 5 --root "$LEVEL_ROOT/level5" --tops-dir "$ALIGN_TOPS"
```

维护者将每张卡保存在工作区外。研究者只收到 `challenge.json`，其中列出候选、开发证据、指标与近零阈值。提交的 `decision.json` 必须给出任务 ID、候选 ID、有符号的数值预测、解释及可反驳的替代解释。维护者按固定研究者身份登记第一次有效提交，同一提交可以复算。下面以第 3 层演示仓库的标准命令，其他层使用相应的包和任务 ID。

```bash
LEVEL_PACKET="$LEVEL_ROOT/level3"
LEVEL_STAGE="$LEVEL_ROOT/tasks/researcher-a-path"
LEVEL_TASK=alignment-head-mlp-path
LEVEL_WORK="$LEVEL_ROOT/work/researcher-a-path"
LEVEL_RUNS="$LEVEL_ROOT/runs"
LEVEL_ID=researcher-a-path

"$ALIGN_PYTHON" -B "$LEVEL_CLI" stage --root "$LEVEL_PACKET" --out "$LEVEL_STAGE" --actor researcher-a
node dist/cli.js run "$LEVEL_TASK" --tasks "tasks,$LEVEL_STAGE" --adapter manual \
  --agent researcher-a --workspace "$LEVEL_WORK" --out "$LEVEL_RUNS" --run-id "$LEVEL_ID"
# 研究者阅读工作区的 challenge.json，并将 decision.json 写入同一工作区。
node dist/cli.js run "$LEVEL_TASK" --tasks "tasks,$LEVEL_STAGE" --adapter manual --resume "$LEVEL_RUNS/$LEVEL_ID"
node dist/cli.js submit verify "$LEVEL_RUNS/$LEVEL_ID" --tasks "tasks,$LEVEL_STAGE"
node dist/cli.js score "$LEVEL_RUNS/$LEVEL_ID" --tasks "tasks,$LEVEL_STAGE" --isolation process
"$ALIGN_PYTHON" -B "$LEVEL_CLI" grade --root "$LEVEL_PACKET" --actor researcher-a \
  --answer "$LEVEL_RUNS/$LEVEL_ID/artifacts/decision.json"
```

只复算固定参考时，在独立的维护者身份下执行以下命令。`--reference-check` 会在专用任务目录生成参考解，以便 `validate` 同时检查有效提交与空提交。实验卡通过标准 CLI 显式加载，工作区的隔离由实际部署提供。

```bash
"$ALIGN_PYTHON" -B "$LEVEL_CLI" stage --root "$LEVEL_PACKET" --out "$LEVEL_ROOT/tasks/path-validation" \
  --actor maintainer-top-development --reference-check
node dist/cli.js validate "$LEVEL_TASK" --tasks "tasks,$LEVEL_ROOT/tasks/path-validation"
"$ALIGN_PYTHON" -B "$LEVEL_CLI" reference --root "$LEVEL_PACKET" --out "$LEVEL_ROOT/reference.json"
"$ALIGN_PYTHON" -B "$LEVEL_CLI" grade --root "$LEVEL_PACKET" --actor maintainer-top-development \
  --answer "$LEVEL_ROOT/reference.json"
```

四张卡均完成参考解验证、空提交验证、运行与恢复、提交校验和进程评分。随后从源数据独立重建公开包与评分端结果，八份清单及四份评分报告全部一致。归档中保留了开发卡、冻结提交、CLI 分数和逐项观测。[四项运行记录](evidence/20261119/levels) · [可移植验收记录](evidence/levels-reference-20261119.json) · [数值与冻结机制测试](../_shared/test_multiscale_levels.py)
