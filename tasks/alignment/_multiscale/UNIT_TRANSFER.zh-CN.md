# L2 单元选择与跨研究验证

Agent 在一个冻结语言模型中自由探索，自选一层、一个 token 位置和 8 个不同的原生 MLP 单元。它可以写代码分析训练激活和逐人脑响应，也可以向开发集查询两次。选定的单元能否在新句子、新参与者和另一项阅读研究中增加预测力，由评分器独立测量。

## 数据和主分

| 分区 | 句子 × 参与者 | 用法 |
|---|---:|---|
| Tuckute baseline | 988 × 5 | 公开逐句文本、单元激活、控制变量和逐人响应。统一读出拟合五人的逐句均值 |
| Tuckute search 开发 | 250 × 1 | 125 个增强句和 125 个抑制句。每次只返回一个开发 Δr |
| Tuckute search 主测试 | 250 × 2 | 另两人、另外 250 句。增强和抑制各占一半 |
| Tuckute modify 迁移 | 500 × 2 | 另外两人和经修改生成的材料，沿用 Tuckute 训练读出 |
| Pereira384 迁移 | 304 × 9 拟合，80 × 9 测试 | 按主题分区，整段留出。冻结层、位置和单元，只在这九人各自的训练段落上重新拟合读出 |

Tuckute 沿用现有 L4 的分半和作者左侧语言网络均值。Pereira 用与 Tuckute 对应的五个左侧语言区，每人将训练分区有完整测量的体素取均值。两项研究均将句子单独送入模型。这衡量单句表征在连续阅读材料中的迁移。Pereira 留出的是新材料，拟合和测试使用相同的九位参与者。[Tuckute 数据说明](https://github.com/gretatuckute/drive_suppress_brains#downloading-data) · [Pereira 数据与刺激](https://web.mit.edu/evlab/sites/default/files/documents/index2.html) · [本仓库使用的原始文件与下载链接](../DATASETS.zh-CN.md)

逐人、逐条件计算 **Δr = r(控制变量 + 8 个单元, 脑响应) − r(仅控制变量, 脑响应)**。两个读出都在相应训练分区标准化特征，拟合固定 ridge（α = 100，截距不惩罚）。控制变量固定为模型自身的 token 数和平均下一 token 惊讶度，取自然对数，跳过首 token。增强和抑制以及每位参与者等权。主分是 `search_delta_r`，保留负值。若一格的脑响应或控制预测恒定，准备数据时报错。联合预测恒定时，该分区的分数记为未定义。Pereira 在全部留出句子上逐人算 Δr，单列报告。

## 模型与对照策略

| 模型 ID | 层数 × 每层单元数 | 单元读出位置 |
|---|---:|---|
| `distilgpt2` | 6 × 3,072 | GPT-2 MLP 激活后、进入 `c_proj` 前 |
| `gpt2-small` | 12 × 3,072 | GPT-2 MLP 激活后、进入 `c_proj` 前 |
| `llama-3.2-1b` | 16 × 8,192 | Llama 门控乘积进入 `down_proj` 前 |

`pre1` 和 `pre2` 分别取末词首个子词前的第一个和第二个 token。准备程序从本地读取权重和分词器，把输入文件的哈希写入公开包。每份选择绑定对应公开包的哈希。

评分器使用两条固定策略对照 Agent。随机策略用种子 73 抽取一层、一个读取位置和 8 个单元。另一条策略在每个层和位置按单元与训练脑响应的绝对 Pearson 相关选前 8，再取这 8 个相关值均值最高的层和位置。两条策略只使用公开训练包。

## 准备和运行

从仓库根目录运行。准备端需要 Python 3.11 或更高版本，以及 NumPy、pandas、h5py、PyTorch 和 Transformers。Agent 读取公开包只需 Python 和 NumPy。在新 checkout 中运行 `npm ci` 和 `npm run build`，生成 `dist/cli.js`。

维护者准备对应模型的本地权重与分词器，并从数据清单取得 Tuckute CSV 和 Pereira 的 NetCDF 文件。以下路径由运行方设置。每个模型使用一个数据包，每位研究者使用独立的身份和实例目录。[数据来源及文件名](../DATASETS.zh-CN.md)

```bash
L2_PYTHON="${L2_PYTHON:-python3}"
L2_CLI="$PWD/tasks/alignment/_shared/unit_transfer_cli.py"
L2_ROOT="$PWD/.cache/l2-unit-transfer"
L2_MODEL=distilgpt2
L2_MODEL_DIR="/path/to/local/$L2_MODEL"
L2_SOURCES="/path/to/source-data"
L2_ACTOR=researcher-01
L2_PACKET="$L2_ROOT/packets/$L2_MODEL"
L2_TASK="alignment-l2-unit-transfer-$L2_MODEL"
L2_STAGE="$L2_ROOT/tasks/$L2_ACTOR"
L2_WORK="$L2_ROOT/work/$L2_MODEL-$L2_ACTOR"

"$L2_PYTHON" "$L2_CLI" prepare --model "$L2_MODEL" --model-dir "$L2_MODEL_DIR" \
  --csv "$L2_SOURCES/brain-lang-data_participant_20230728.csv" \
  --pereira "$L2_SOURCES/assy_Pereira2018_language.nc" --root "$L2_PACKET"
"$L2_PYTHON" "$L2_CLI" stage --root "$L2_PACKET" --actor "$L2_ACTOR" --out "$L2_STAGE/$L2_TASK"
```

已有输入包可直接从 `stage` 开始。维护者可用 `baselines --root "$L2_PACKET"` 单独计算两条固定策略的分数。

只给 Agent 挂载自己的工作区。数据包的 `owner/`、原始数据和查询账本由维护者持有。用标准入口创建工作区，随后在维护者终端启动开发查询服务。服务通过该工作区的 `dev/` 交换 JSON，支持无网络的 Agent。

```bash
node dist/cli.js run "$L2_TASK" --tasks "tasks,$L2_STAGE" --adapter manual \
  --agent "$L2_ACTOR" --workspace "$L2_WORK" --out "$L2_ROOT/runs" --run-id "$L2_MODEL-$L2_ACTOR"
"$L2_PYTHON" "$L2_CLI" serve-dev --root "$L2_PACKET" --actor "$L2_ACTOR" --exchange "$L2_WORK/dev"
```

接入自动 Agent 时，维护者先在单独终端启动上述 `serve-dev`。使用 `run --adapter command --isolation docker --image "$AGENT_IMAGE" --command "$AGENT_COMMAND"` 配合同样的任务、身份和工作区参数，即可由 Agent 自行探索和查询。镜像由运行方指定，工作区只挂载公开训练材料及开发邮箱。command adapter 完成后，可对生成的运行包执行下方的 `score` 命令。

Agent 可以在工作区运行 `python query.py candidate.json`。请求包含 `packet_sha256`、从零开始的 `layer`、`position` 和 `units`。同一组重复请求返回原回执，不重复扣次数。SQLite 在同一事务内检查查询额度和冻结状态。最终交付工作区根目录的 `choice.json` 和 `strategy.py`。策略约定为 `python strategy.py PUBLIC_DIR FEEDBACK_JSON`，将最终选择作为 JSON 输出到标准输出。反馈文件是按顺序排列的查询回执数组，零次查询时为 `[]`。运行结束后停止开发查询服务。

评分时，维护者先冻结选择、源码哈希和开发反馈，再将代码放入断网 Docker，只挂载只读公开包、冻结的反馈和临时输出。复跑必须给出相同的层、位置及 8 个单元，随后评分器计算三个分区的成绩。相同提交可重复评分。使用包含 `/opt/alignment/worker.py` 的本地镜像，按不可变镜像 ID 评分。下例从仓库根目录构建镜像。[评测镜像](../_env/Dockerfile.server)

```bash
L2_RUN="$L2_ROOT/runs/$L2_MODEL-$L2_ACTOR"
node dist/cli.js run "$L2_TASK" --tasks "tasks,$L2_STAGE" --adapter manual --resume "$L2_RUN"
git archive HEAD tasks/alignment/_env tasks/alignment/_shared | \
  docker build -t bpb-alignment-worker -f tasks/alignment/_env/Dockerfile.server -
L2_IMAGE=$(docker image inspect --format '{{.Id}}' bpb-alignment-worker)
node dist/cli.js score "$L2_RUN" --tasks "tasks,$L2_STAGE" --isolation docker --inference-image "$L2_IMAGE"
```

`scores.json` 写入三个汇总指标，`l2-measurement.json` 包含复跑回执、逐人结果和 agent／随机／相关前八三行对照。管理者也可以在独立验证身份上使用 `stage --reference-check` 和 `bp-bench validate` 检查参考解及空提交。模型通道、评分、并发查询上限和冻结的回归测试可用以下命令执行。

```bash
"$L2_PYTHON" -B tasks/alignment/_shared/test_unit_transfer.py
```
