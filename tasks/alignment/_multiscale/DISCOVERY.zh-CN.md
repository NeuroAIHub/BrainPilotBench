# L1 与 L3 的准备、查询和盲评

两个任务沿用 L2/L4 的研究者工作区、SQLite 查询账本和断网 Docker 复跑。每种模型各准备一份公开包和一份维护者包，每次独立运行分配新的 actor。任务窗口 30 分钟，API token 总额不设上限。模型适配 `distilgpt2`、`gpt2-small` 和 `llama-3.2-1b`，须提供完整本地权重和分词器。准备端使用 NumPy、pandas、PyTorch、Transformers，分数复跑镜像需包含仓库的 alignment worker。[L1 协议](../alignment-l1-cell-tuning/README.md) · [L3 协议](../alignment-l3-circuit-paths/README.md) · [数据文件说明](../DATASETS.zh-CN.md)

## 准备封存包

从仓库根目录执行 `npm run build`。以下变量指向本机缓存。L1 使用作者 v1 两个文件，文件名分别绑定作者文件 ID 47389075、47389087，读入前验证大小和 SHA-256。已有这两份文件时直接使用其目录。也可运行 `python tasks/alignment/_shared/multiscale_levels_cli.py fetch-unit --jamali-dir "$JAMALI"` 获取。[Jamali 作者发布](https://doi.org/10.6084/m9.figshare.26046127.v1)

```bash
PYTHON=python3
SHARED="$PWD/tasks/alignment/_shared"
BASE="$PWD/.cache/alignment-discovery/v1"
MODEL=distilgpt2
WEIGHTS=/path/to/local/distilgpt2
JAMALI=/path/to/jamali
CSV=/path/to/brain-lang-data_participant_20230728.csv

"$PYTHON" -B "$SHARED/cell_tuning_cli.py" prepare --model "$MODEL" --model-dir "$WEIGHTS" \
  --jamali-dir "$JAMALI" --root "$BASE/$MODEL/l1"
"$PYTHON" -B "$SHARED/circuit_paths_cli.py" prepare --model "$MODEL" --model-dir "$WEIGHTS" \
  --csv "$CSV" --root "$BASE/$MODEL/l3"
```

L3 的精确评分需要原模型。移动封存包或权重后，维护者可设置 `BPB_CIRCUIT_MODEL_DIR`。评分端会重新核对权重、分词器和运行时指纹。L1 在准备结束后可单凭封存数组评分。

## 为一个研究者建工作区

以下是 L1 示例。L3 替换为 `LEVEL=l3`、`CLI="$SHARED/circuit_paths_cli.py"`、`TASK="alignment-l3-circuit-paths-$MODEL"`。每次研究使用新的 actor、工作区和提交目录。

```bash
LEVEL=l1
CLI="$SHARED/cell_tuning_cli.py"
TASK="alignment-l1-cell-tuning-$MODEL"
ACTOR=researcher-01
PACKET="$BASE/$MODEL/$LEVEL"
STAGE="$BASE/stage/$LEVEL/$MODEL/$ACTOR"
WORK="$BASE/work/$LEVEL/$MODEL/$ACTOR"
RUNS="$BASE/runs/$LEVEL/$MODEL"
"$PYTHON" -B "$CLI" stage --root "$PACKET" --actor "$ACTOR" --out "$STAGE/$TASK"

node dist/cli.js run "$TASK" --tasks "tasks,$STAGE" --adapter manual --agent "$ACTOR" \
  --workspace "$WORK" --out "$RUNS" --run-id "$ACTOR"
```

维护者在另一个终端运行开发服务。每个 actor 的 `dev/` 单独收发开发回执。使用 Codex 或 BrainPilot 时，将自己的工作区和只读公开输入提供给研究工具。原始数据源、完整封存包、模型定位文件、其他 actor 的回执和评测脚本留在维护者侧。使用远程模型时，科学工具输出在本机过滤，仅传汇总统计、候选与查询回执。

```bash
"$PYTHON" -B "$CLI" serve-dev --root "$PACKET" --actor "$ACTOR" --exchange "$WORK/dev"
```

L3 另开一个维护者终端为同一 actor 运行公开训练探测服务。研究者可用它对任意合法路径做精确干预。相同请求返回原回执，训练探测不限次数，开发额度单独登记。

```bash
"$PYTHON" -B "$CLI" serve-train --root "$PACKET" --actor "$ACTOR" --exchange "$WORK/train"
# 在研究工作区执行
python query.py choice.json --exchange train --timeout 600
```

训练回执包含 `probe`、`choice`、`train_score` 及 `fold_gains`。研究期间可从 `train/*.reply.json` 收集并按 `probe` 排序。L3 复跑时工作目录下的 `training_feedback.json` 由维护者从账本重建，含本 actor 全部已完成的训练回执，零次时为 `[]`。BrainPilot 原生 session 的训练邮箱同样位于 session 的 `train/` 子目录。

研究者运行 `python query.py choice.json`。L3 在较慢的 CPU 上可用 `--timeout 600` 延长客户端等待。相同选择重复查询返回原回执。两次不同选择之后额度用尽，回执包含 `query`、规范化的 `choice` 和 `dev_score`。研究者提交的 `python strategy.py public feedback.json` 应输出完整选择。复跑提供只读公开包、冻结脚本和维护者记录的回执。零次开发查询时 `feedback.json` 为 `[]`。

## 回收与评分

```bash
RUN="$RUNS/$ACTOR"
node dist/cli.js run "$TASK" --tasks "tasks,$STAGE" --adapter manual --resume "$RUN"
node dist/cli.js submit verify "$RUN" --tasks "tasks,$STAGE"
IMAGE=$(docker image inspect --format '{{.Id}}' bpb-alignment-worker)
node dist/cli.js score "$RUN" --tasks "tasks,$STAGE" --isolation docker --inference-image "$IMAGE"
```

BrainPilot 原生运行可将 `--adapter manual --workspace "$WORK"` 换为 `--adapter brainpilot --base-url "$BRAINPILOT_BASE_URL" --workspace-root "$WORK"`。运行时会在 workspace root 下建立 session 子目录，维护者把 `serve-dev --exchange` 指向该 session 的 `dev/`。原生 adapter 完成后直接校验并评分。

评分先冻结选择与脚本 SHA-256，用断网 Docker 在 2 核、2 GiB、120 秒内复跑，再用维护者包测量。标准指标在 `scores.json`，细目在 `l1-measurement.json` 或 `l3-measurement.json`。维护者可给独立验收 actor 执行 `stage --reference-check`，再用 `BPB_INFERENCE_IMAGE="$IMAGE" node dist/cli.js validate "$TASK" --tasks "tasks,$STAGE"` 验证参考解与空提交。离线回归入口为 `python -B tasks/alignment/_shared/test_discovery.py`。
