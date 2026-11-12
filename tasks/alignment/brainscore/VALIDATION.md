# Brain-Score scale-up 验证记录

日期：2026-11-11。执行边界：没有下载数据、刺激或模型权重；获取了官方软件源码、依赖和元数据。Pereira384 的真实验证复用本机原有文件，所有新缓存、参考结果和 staged task 均在仓外。原环境、原缓存和历史成绩没有覆盖。

机器可读汇总：[validation-summary.json](evidence/20261111/validation-summary.json)。本目录证据只包含哈希、版本、指标和诊断，不包含数据、刺激文本、权重或预测数组。

## 软件与方法

| 环境 | 上游 commit | 关键版本 |
|---|---|---|
| Vision | `c5608668783fe654f83611305fb7e717db0a0cbf` | Brain-Score 2.4.4、sklearn 1.5.2 |
| Language | `cc9f623151b5e64be1919c8a8a8b08edc317b784` | Brain-Score 2.3.1、sklearn 1.7.2 |

两者固定 NumPy 1.26.4、Torch 2.6.0、xarray 2022.3.0；完整依赖见 [environments](environments)。Owner 使用 Python 3.11.18，Docker 为 3.11.2；分别验证源码内容指纹和数值包一致性。

本地镜像 ID：

- Language：`sha256:df63a77d40f943c26dd069cdd35e73424cb697116d3eb5d0118c1d0477c258f0`
- Vision：`sha256:8861b2c0f91a93a3ee551cf2c0f78da096b0652db86fde27999d6ba1c540e382`

上游协议的审计与关键区别见 [SOURCE_AUDIT.md](SOURCE_AUDIT.md)：视觉为不裁剪的 `r²/ceiling`，语言为裁剪的 `r/ceiling`；Futrell raw 是绝对 Pearson r，保留 signed r；语言使用官方 RidgeGCVTorch；Freeman public version 为 1。

## 无新数据验证

- **21 项 Python 契约检查、4 项 Node catalog 检查通过**：白名单、源码版本、无站点包 CLI、ID 对齐、泄漏、缺失掩码、文件完整性、禁止虚假准入、归一化以及向量化描述性计算。
- **24 个实例、36 个 benchmark × candidate case 通过官方合成计算**：Language 14 个实例/20 cases；Vision 10 个实例/16 cases。每个实例还生成实验 task，拒绝未显式标记的合成 staging，公开工作区没有答案程序。
- **容器评分检查通过**：Language T1、T2、行为；Vision T1、T2，维护者程序均为 1。两环境的固定答案程序即使重写输入哈希并打印伪造成功标记，也在扰动输入上得到 0；不存在的镜像得到 `scoring_failed` 和 null，未错误记成 0。
- **5 组模型/来源绑定检查通过**：Fedorenko/Blank/Futrell 官方入口的上下文和 cache export；随机小 GPT 的重复调用重置与 bit-surprisal；四视觉脑区固定映射及像素/图像预处理；官方时间窗/重复平均；本地 NetCDF、乱序 CSV 和 ZIP 合并。测试中的替代原始数据和 ceiling 明确为合成，不能证明真实来源等价。

最终数值矩阵：[Language](evidence/20261111/synthetic-language-matrix.json)、[Vision](evidence/20261111/synthetic-vision-matrix.json)。隔离评分证据：[Language](evidence/20261111/synthetic-language-grading.json)、[Vision](evidence/20261111/synthetic-vision-grading.json)。测试中的跨生态 skip 是不适用项；独立环境内适用项全部通过。

## Pereira384 真实验证

输入：本机已有原始 assembly、对应的三层 ceiling、固定 revision `2290a62682d06624634c1f46a6ad5be0f47f38aa` 的 distilgpt2 模型/tokenizer。逐文件核对上游 SHA1 或 Hub Git/LFS 校验信息，再记录 SHA256；没有重新下载。使用最终层 `transformer.h.5`，CPU float32，按官方 passage 上下文计算。

| 项目 | 观测 |
|---|---:|
| 刺激 | 384 |
| 测量单元 | 12,155 |
| 模型特征 | 768 |
| 官方 raw | 0.07885228013320371 |
| ceiling | 0.13521249808656496 |
| 归一化分数 | 0.5831730146921874 |
| live/cache 等价 | 分数、10 折预测、单元指标、alpha 通过 |
| 维护者基线任务分数 | analysis_success = 1 |

证据：[官方等价](evidence/20261111/pereira384-equivalence.json)、[cache 身份](evidence/20261111/pereira384-cache-manifest.json)、[模型身份](evidence/20261111/pereira384-model-manifest.json)、[隔离评分](evidence/20261111/pereira384-grade.json)。容差为 atol=1e-6、rtol=1e-5，仍属实验配置。

已实测现有 CLI 的 `prepare → manual run → resume/产物回收 → submit verify → Docker score → leaderboard`，以及 task schema 验证。结果：[CLI score](evidence/20261111/pereira384-cli-scores.json)、[leaderboard](evidence/20261111/pereira384-leaderboard.json)。此处的 agent 标记明确为 `maintainer-baseline-not-independent-agent`。使用外部 task root 时，应将仓库 `tasks` 放在 `--tasks` 第一项，使 CLI 读取现有 categories.yaml。

准备耗时约 121 秒、owner 峰值 RSS 约 2.68 GiB；保存结果、重跑和控制合计评分耗时约 72 秒。worker 限制为 2 CPU、8 GiB、单次 900 秒。这是一个维护者基线的资源观测，不代表其他来源或 Agent 的预算已校准。[资源记录](evidence/20261111/pereira384-resources.json)

还与旧 commit `3b4fde5d6f53a69c652c7a1128397549995547b0` 已有参考结果进行了迁移核对：对齐后的最终层特征与三个标量分数完全相同，10 折 train/test 身份、alpha、预测及逐单元相关均一致。范围仅为这个候选/实验/层；未改写历史成绩，也未继承旧任务的准入状态。[迁移核对](evidence/20261111/pereira384-migration.json)

本机重查入口：`/tmp/bpb-bs-real-task-20261111`、`/tmp/bpb-bs-real-runs-20261111/baseline`、`/tmp/bpb-bs-pereira384-inputs-20261111`。这些是临时执行产物；持久的审阅证据已复制到本目录。

## 当前准入边界

`npm run test:collection`、`npm run catalog:check` 通过：正式清单仍为 **112 runnable + 6 candidate = 118**。本次没有把 24 个计划实例或合成例子计入正式数量。

Pereira384/distilgpt2 的 preflight 当前只剩来源许可确认和独立 Agent 验收。其他实例还需缺失的本地数据/刺激/ceiling/权重、对应真实等价与资源校准。Futrell 的 2025 年对齐修正是否进入固定 artifact 单独保留为数据版本缺口；许可与数据修正不能由合成测试消除。
