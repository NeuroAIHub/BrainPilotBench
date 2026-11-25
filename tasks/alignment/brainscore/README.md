# Brain-Score alignment scale-up

本扩展有 **6 个来源任务**。每个任务提交该来源的单模型复现和逐基准比较，合计 18 个复现子项、9 个比较结果。单模型子项保留原 ID，可单独运行和评分。

| 范围 | 当前状态 |
|---|---|
| 来源和协议 | 6 个来源家族、9 个官方 benchmark，固定源码 commit、原文件对象锁和协议 |
| 任务清单 | `instances.json` 的 `instances` 列出 6 个来源任务（T2），`subtasks` 列出按来源归属的 18 个单模型子项（T1） |
| 官方方法 | 视觉 PLS、语言 RidgeGCVTorch、Futrell 直接行为比较；调用固定的上游实现 |
| 运行环境 | Vision / Language 分开；软件版本、源码指纹、依赖锁和本地 Docker 镜像已冻结 |
| 评分 | 整题通过分、逐模型复现分、逐基准比较分。每个基准独立执行一次扰动重跑 |
| 真实验证 | Pereira384 × distilgpt2 官方/cache 等价及完整 CLI 评分通过；384 个刺激、12,155 个单元 |
| 正式准入 | 新增 canonical task 仍为 0；实验 staging 与合成例子不计入正式数量 |

2026-11-11 的 Pereira384 × distilgpt2 真实运行得到 raw `0.07885228013320371`、ceiling `0.13521249808656496` 和归一化分数 `0.5831730146921874`，当时的维护者基线得到 `analysis_success=1`。2026-11-23 的来源任务合并使用合成输入验证。[验证记录](VALIDATION.md)

## 文件与入口

- [任务与子项说明](TASK_GUIDE.zh-CN.md)列出各来源的候选、测量、提交产物和就绪程度。
- [BASELINE_AUDIT.md](BASELINE_AUDIT.md)：逐项核验官方基线；10 个语言组合有网页成绩，视觉 public 配置与普通榜单不能直接对分，并列出源码测试、教程示例和本地参考的区别。
- [sources.json](sources.json)、[candidates.json](candidates.json)、[instances.json](instances.json)：显式白名单、固定模型和逐实例验收证据。
- [source-assets.json](source-assets.json)：16 个上游对象的原文件名、SHA1、版本和来源；没有远程取回这些对象。
- [model-assets.json](model-assets.json)：两个语言模型固定 revision 的文件元数据，用于验证已有文件。
- [software-lock.json](software-lock.json)、[environments](environments)：数值依赖、源码内容指纹、完整安装版本和本地镜像身份。
- [SOURCE_AUDIT.md](SOURCE_AUDIT.md)：官方方法、模型、来源许可与版本审计，含固定链接。
- [INPUT_CONTRACT.md](INPUT_CONTRACT.md)：Agent 可见的输入、计算和输出契约。
- [brainscore_cli.py](../_shared/brainscore_cli.py)：统一入口；没有数据或权重下载命令。

清单操作只需标准库，不导入 Torch/Brain-Score：

```bash
python3 -B tasks/alignment/_shared/brainscore_cli.py validate
python3 -B tasks/alignment/_shared/brainscore_cli.py list
python3 -B tasks/alignment/_shared/brainscore_cli.py list --subtasks
python3 -B tasks/alignment/_shared/brainscore_cli.py preflight --require-ready
python3 -B tasks/alignment/_shared/brainscore_cli.py draft --output /tmp/bs-contract-drafts
```

`list`、`draft` 和 `preflight` 默认处理 6 个来源任务，加 `--subtasks` 可处理 18 个单模型子项。`list` 输出的 `subtask_ids` 和 `parent_id` 可以双向查找。向 `bundle --instance`、`fixture-instance --instance` 或 `preflight --instance` 传入任务或子项 ID 即可单独选择。`preflight --require-ready` 对未完成验收返回 2，并逐项列出缺口。

## 环境与本地准备

两套环境均为 Python 3.11，但 sklearn 不同：Vision 固定 1.5.2，Language 固定 1.7.2。当前本机解释器如下；临时目录不是发布依赖，其他机器须按 `environments/*.requirements.lock.txt` 安装独立软件环境并通过 `runtime` 检查。不要覆盖旧 Pereira 环境。

```bash
BS_LANGUAGE_PY=/tmp/bpb-bs-language-env-20261111/bin/python
BS_VISION_PY=/tmp/bpb-bs-vision-env-20261111/bin/python
BS_CLI=tasks/alignment/_shared/brainscore_cli.py
"$BS_LANGUAGE_PY" -B "$BS_CLI" runtime --ecosystem language
"$BS_VISION_PY" -B "$BS_CLI" runtime --ecosystem vision
```

`worker-context --ecosystem NAME --base-image sha256:ID --output DIR` 从已安装的软件导出构建目录。基础镜像须已存在并包含兼容 Python/Torch。使用命令输出的 `DOCKER_BUILDKIT=0 docker build --network=none --pull=false ...` 构建；BuildKit 会把裸 image ID 当作远端镜像名。新机器生成新镜像后，维护者需冻结实际 ID 并重跑验证。评分器检查镜像身份、数值包版本和上游源码；镜像内没有 owner 分析答案。

所有原文件、模型、缓存、参考结果和 task staging 放在仓外的新目录；已有输出不会覆盖。`audit-sources` 校验上游 SHA1 并记录 SHA256，缺文件退出 2，不联网。视觉需要 assembly、刺激 CSV 和图片 ZIP；Pereira 还需要对应实验的三层 ceiling。

以下命令仅处理已存在的文件；文件名和完整镜像 ID 从锁文件读取：

```bash
"$BS_LANGUAGE_PY" -B "$BS_CLI" audit-sources \
  --raw /srv/bs/raw/pereira --benchmark Pereira2018.384sentences-ridge
"$BS_LANGUAGE_PY" -B "$BS_CLI" seal-model --candidate distilgpt2 \
  --source /srv/existing-hf-snapshot --output /srv/bs/models/distilgpt2
"$BS_LANGUAGE_PY" -B "$BS_CLI" prepare \
  --raw /srv/bs/raw/pereira --benchmark Pereira2018.384sentences-ridge \
  --candidate distilgpt2 --model-dir /srv/bs/models/distilgpt2 \
  --image-digest sha256:FROZEN_LANGUAGE_IMAGE_ID \
  --output /srv/bs/cache/pereira384-distil --reference-output /srv/bs/owner/equivalence
"$BS_LANGUAGE_PY" -B "$BS_CLI" bundle \
  --instance alignment-bs-pereira2018-384sentences-distilgpt2-reproduce \
  --packet /srv/bs/cache/pereira384-distil --output /srv/bs/inputs/pereira384
"$BS_LANGUAGE_PY" -B "$BS_CLI" stage --inputs /srv/bs/inputs/pereira384 \
  --verification /srv/bs/owner/equivalence/verification.json --output /srv/bs/tasks/pereira384
```

`prepare` 保留官方 constructor/预处理，只替换远程对象解析。运行固定候选后，它比较 live 与 cache 的分数、逐折预测、单元指标及 alpha。证据留在 owner 目录，任务仅获得公开输入。`pixels` 无需模型文件；AlexNet 使用通过官方发布校验前缀验证的 `alexnet.pth`；语言模型验证固定 Hub 元数据对应的 safetensors/tokenizer 字节。

上例单独打包了 Pereira384 的 distilgpt2 子项。要运行完整的 `alignment-bs-pereira2018-compare`，对 243 句和 384 句两个实验分别准备 distilgpt2、gpt2-small 缓存，再用该任务 ID 和四个 `--packet` 一次打包。同一基准两候选的目标、ID、协议和排除项必须相同。提交会产生四个复现分和两个比较分。

## 执行和评分

实验 task 使用现有 CLI，过程与旧任务一致。维护者须为 Agent 的开发环境提供同一套软件依赖；task setup 只复制公开输入，不安装依赖或复制解答。独立 command Agent 可用 runner 的 `--isolation docker --image AGENT_IMAGE`，并在该开发镜像中安装匹配的依赖：

```bash
node dist/cli.js prepare TASK_ID --tasks tasks,/srv/bs/tasks --workspace /srv/bs/workspace
node dist/cli.js run TASK_ID --tasks tasks,/srv/bs/tasks --adapter manual \
  --agent AGENT_ID --workspace /srv/bs/workspace --out /srv/bs/runs --run-id RUN_ID
# 完成 submission/analyze.py 及结果后，通过 run --adapter manual --resume RUN_DIR 回收产物。
node dist/cli.js submit verify /srv/bs/runs/RUN_ID --tasks tasks,/srv/bs/tasks
node dist/cli.js score /srv/bs/runs/RUN_ID --tasks tasks,/srv/bs/tasks \
  --isolation docker --inference-image sha256:FROZEN_LANGUAGE_IMAGE_ID
```

维护者可用 `reference-submission --output DIR` 导出测试基线，用 `reference --inputs DIR --output DIR` 产生核对结果；两者从不由 task setup 安装进 Agent 工作区。单独调用 `evaluate --inputs DIR --submission DIR --saved-results DIR --output DIR --image IMAGE` 可保存详细 grade。不要把维护者基线记为独立 Agent 验收。

## 无新资产验证

```bash
BPB_ALIGNMENT_PYTHON="$BS_LANGUAGE_PY" npm run test:alignment-brainscore
"$BS_LANGUAGE_PY" -B tasks/alignment/_shared/test_brainscore_scientific.py \
  --ecosystem language --image bpb-bs-language-offline:20261111 --output /tmp/bs-language-tests
"$BS_VISION_PY" -B tasks/alignment/_shared/test_brainscore_scientific.py \
  --ecosystem vision --image bpb-bs-vision-offline:20261111 --output /tmp/bs-vision-tests
"$BS_LANGUAGE_PY" -B tasks/alignment/_shared/test_brainscore_bindings.py --ecosystem language
"$BS_VISION_PY" -B tasks/alignment/_shared/test_brainscore_bindings.py --ecosystem vision
```

合成输入用 `fixture-instance --instance ID --output DIR` 生成。导出合成任务需要 `--allow-synthetic`，任务 ID 加 `example-`。回归测试核对各来源任务内的复现是否与独立子项一致，并分别检验错误的预测、排名和逐基准扰动。

输入数组使用只读 mmap，每文件上限 8 GiB。同序候选避免复制全矩阵。voxel 描述性相关按列向量化，控制输入只修改目标基准的指定数组。评分输出上限为 512 MiB，单次 worker 默认为 2 CPU、8 GiB、900 秒。导出任务的评分总时限为单基准 45 分钟、双基准 75 分钟，给第二个基准的参考计算和隔离重跑各预留 15 分钟。完整视觉 pixels 的资源需求仍须用真实规模校准，可通过 `evaluate --memory/--cpus/--timeout` 调整。

## 未完成的真实验收

2026-11-25 已从官方来源下载 AlexNet 和 GPT-2 small，并用 `seal-model` 核验权重及 GPT-2 分词器。逐文件 SHA-256 见 [AlexNet 清单](evidence/20261125/alexnet-model-manifest.json)和 [GPT-2 small 清单](evidence/20261125/gpt2-small-model-manifest.json)。

其余来源原文件、刺激和 Pereira243 ceiling 仍待准备，相应真实分数、资源校准和 T2 真实比较待执行。校验本地资产后，执行 `prepare → bundle → evaluate → stage`。

许可审查已完成可公开查证部分；未找到原权利人明确授权的资产保留缺口，不把代码 MIT 当数据许可。Natural Stories 明确 CC BY-NC-SA 4.0；固定 Futrell artifact 是否包含作者 2025 年阅读时间对齐修正仍需核查，详见来源审计。

正式准入还需独立 Agent 校准、相应资源验收和来源条件确认。Pereira384 单模型子项保留了原有的真实输入等价性证据。
