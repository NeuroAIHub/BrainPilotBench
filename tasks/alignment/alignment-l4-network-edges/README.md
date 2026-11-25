# L4 · 五个语言脑区的共变边预测

研究 Agent 在冻结的语言模型中为五个左侧语言脑区各找一组 MLP 单元。任务检验这些单元能否在新句子和新参与者上重现「增强句相对抑制句，哪些脑区对更同步、哪些更不相关」。同一次提交冻结五组单元、选择代码和主分预测值。

## 数据与评分

数据来自 Tuckute 的逐参与者 CSV。每个实例绑定一套本地模型权重、分词器、数据源和公开包指纹。模型适配器支持 `distilgpt2`、`gpt2-small` 和 `llama-3.2-1b`。准备时须提供对应的完整本地权重。[源文件及数据说明](../DATASETS.zh-CN.md) · [模型适配器](../_shared/unit_transfer/features.py)

| 分区 | 句子 × 参与者 | 研究者可见内容 |
|---|---:|---|
| 基线训练句 | 988 × 5 | 文本、单元激活、五区逐人响应、条件、扫描编号、token 数与平均 surprisal |
| Search 开发 | 250 × 1 | 每个不同映射的一条标量回执，最多两次 |
| Search 盲测 | 250 × 2 | 冻结并通过复跑后由维护者评分 |

开发和盲测各含 125 个增强句（D）和 125 个抑制句。三个分区的句子和参与者互斥。新版使用自己的固定分半键，旧 L4 参考卡的分数对应旧切分。五个 ROI 的顺序和十条无向边的端点均写在 `public/protocol.json`。训练包的 `units.npy` 轴为句子、层、读取位置、单元，`responses.npy` 轴为句子、参与者、脑区；`items.json` 中的 `runs` 是逐句、逐参与者的 session/run 标识。

1. 每个脑区选 **8 个**原生单元。各区可独立选一层和一个位置。层号从 0 起，`pre1` / `pre2` 为末词首个 token 之前的第一个 / 第二个 token。同一 `(layer, unit)` 在全部五组中最多出现一次。
2. 每个单元用公开训练句的均值和总体标准差标准化，零标准差按 1 处理，组内等权平均。对每名测试参与者，模型信号和人脑响应都在条件及扫描 session/run 内去均值，分别计算 D 和 S 条件下的十个脑区对相关，取逐边的 D 减 S。
3. 每位参与者得分为两侧十个变化值之间的 Pearson 相关。主分 **`network_edge_r`** 对留出参与者等权平均，保留负值。常数组造成相关未定义时，开发回执为 `null`，盲测报告该参与者未定义，该提交不产生有效主分。[评分实现](../_shared/network_edges/scoring.py)

维护者同时评估只用训练数据选单元的脑区特异性基线和固定种子随机组。特异性基线按单元与各脑区特异响应的协方差依次分配单元，再选平均协方差最大的共同层和位置。对每个有效映射，评分器枚举 5! 种 ROI 标记排列，对所有参与者使用同一排列，报告 119 个打乱映射的均值和单侧精确置换 p 值。事前预测的绝对误差单列；基准用它衡量 Agent 对自己所选映射的判断。这里的边表示逐句响应共变。

## Agent 提交

工作区根目录交付 `choice.json` 和仅依赖公开包、冻结回执及评分镜像内库的 `strategy.py`。以下为提交结构示例，指纹须取本次公开包。ROI 名逐字匹配协议。

```json
{
  "packet_sha256": "<SHA-256 of public/manifest.json>",
  "groups": {
    "lang_LH_IFGorb":  {"layer": 0, "position": "pre1", "units": [0,1,2,3,4,5,6,7]},
    "lang_LH_IFG":     {"layer": 0, "position": "pre1", "units": [8,9,10,11,12,13,14,15]},
    "lang_LH_MFG":     {"layer": 1, "position": "pre2", "units": [0,1,2,3,4,5,6,7]},
    "lang_LH_AntTemp": {"layer": 1, "position": "pre2", "units": [8,9,10,11,12,13,14,15]},
    "lang_LH_PostTemp":{"layer": 2, "position": "pre1", "units": [0,1,2,3,4,5,6,7]}
  },
  "predicted_edge_r": 0.10
}
```

运行 `python query.py choice.json` 可取得 `{"query": 1, "choice": …, "dev_edge_r": …}`。开发查询可省略预测值；同一映射调换组内顺序或改变预测值只返回原回执。最终预测须在 [−1, 1] 内，按六位小数冻结。独立工作目录中的 `python strategy.py public feedback.json` 应向标准输出打印与提交一致的完整选择，包括预测。反馈是按查询顺序排列的回执数组，未查询时为 `[]`。复跑使用断网 Docker，仅挂载公开包、冻结脚本和回执，限 120 秒、2 CPU、2 GiB。

## 准备与运行

在仓库根目录构建 CLI（`npm ci`、`npm run build`）。准备端依赖 NumPy、pandas、PyTorch 和 Transformers，模型及 CSV 路径由维护者指定。每款模型共用一个封存包，每次独立科研运行使用新的 actor 和任务实例目录。标准任务时限 30 分钟，任务未设 API token 总额。

```bash
L4_PYTHON="${L4_PYTHON:-python3}"
L4_CLI="$PWD/tasks/alignment/_shared/network_edges_cli.py"
L4_ROOT="$PWD/.cache/l4-network-edges"
L4_MODEL=distilgpt2
L4_MODEL_DIR="/path/to/local/$L4_MODEL"
L4_CSV="/path/to/brain-lang-data_participant_20230728.csv"
L4_PACKET="$L4_ROOT/packets/$L4_MODEL"
L4_ACTOR=researcher-01
L4_STAGE="$L4_ROOT/tasks/$L4_ACTOR"
L4_TASK="alignment-l4-network-edges-$L4_MODEL"
L4_WORK="$L4_ROOT/work/$L4_MODEL-$L4_ACTOR"
L4_RUN="$L4_ROOT/runs/$L4_MODEL-$L4_ACTOR"

"$L4_PYTHON" -B "$L4_CLI" prepare --csv "$L4_CSV" --model "$L4_MODEL" \
  --model-dir "$L4_MODEL_DIR" --root "$L4_PACKET"
"$L4_PYTHON" -B "$L4_CLI" stage --root "$L4_PACKET" --actor "$L4_ACTOR" --out "$L4_STAGE/$L4_TASK"
node dist/cli.js run "$L4_TASK" --tasks "tasks,$L4_STAGE" --adapter manual \
  --agent "$L4_ACTOR" --workspace "$L4_WORK" --out "$L4_ROOT/runs" --run-id "$L4_MODEL-$L4_ACTOR"
```

维护者在独立终端运行开发服务。服务等待工作区的 `dev/` 邮箱出现；研究完成后可停止服务。给 Agent 的容器只挂载自己的工作区。原始 CSV、完整数据包、任务检查脚本和 SQLite 账本保存在维护者一侧。

```bash
"$L4_PYTHON" -B "$L4_CLI" serve-dev --root "$L4_PACKET" --actor "$L4_ACTOR" --exchange "$L4_WORK/dev"
```

要接入本地 Codex，可以由它在上述隔离工作区完成提交。BrainPilot 原生入口为 `node dist/cli.js run "$L4_TASK" --tasks "tasks,$L4_STAGE" --adapter brainpilot --base-url "$BRAINPILOT_BASE_URL" --workspace-root "$BRAINPILOT_WORKSPACE_ROOT" --agent "$L4_ACTOR" --out "$L4_ROOT/runs" --run-id "$L4_MODEL-$L4_ACTOR"`。该运行时在 workspace root 下按 session ID 建立工作区，维护者将同一 actor 的 `serve-dev --exchange` 指到相应 session 的 `dev/`。使用远程推理时，在宿主侧过滤工具输出，仅转发汇总统计、候选映射和回执，原始句子和逐人逐句响应留在本地。

在手工工作区提交后，用下面的 `--resume` 回收产物；自动 adapter 完成后可直接执行 `score`。示例使用本地已构建、包含 `/opt/alignment/worker.py` 的评分镜像。[评分镜像定义](../_env/Dockerfile.server)

```bash
node dist/cli.js run "$L4_TASK" --tasks "tasks,$L4_STAGE" --adapter manual --resume "$L4_RUN"
L4_IMAGE=$(docker image inspect --format '{{.Id}}' bpb-alignment-worker)
node dist/cli.js score "$L4_RUN" --tasks "tasks,$L4_STAGE" --isolation docker --inference-image "$L4_IMAGE"
```

`scores.json` 记录主分、相对脑区特异性基线的增益、预测误差、打乱映射均值和 ROI 置换 p 值。`l4-measurement.json` 保存冻结指纹、隔离复跑回执、两条固定基线及逐人十条边。维护者可以用独立 actor 执行 `stage --reference-check`，再用 `BPB_INFERENCE_IMAGE="$L4_IMAGE" node dist/cli.js validate "$L4_TASK" --tasks "tasks,$L4_STAGE"` 验证参考提交和空提交。离线合成回归入口为 `python -B tasks/alignment/_shared/test_network_edges.py`。
