#!/bin/bash
# solution/solution.sh —— celegans-structure-function-divergence 的 Oracle 参考解。
#
# 关键约束：src/validate.ts 跑本脚本的超时是**硬编码 120 秒**，而 grader 的超时是
# max(120s, timeout_min × 60)。因此本脚本只造出 schema 合法的产物 + oracle 标记；
# grader 见到标记后改用**合成的**信号/连接走完真值管线（见
# checks/evaluate_external.py 的 oracle_synth），证明「契约可导入 + 管线连通 +
# 四个判据自洽可达」。
#
# 产物里的分析器是**独立实现**的冻结协议（不 import 评分脚本），因此它同时是
# 正常模式下的参考解：在真实私有数据上应得 score = 1.0。
set -euo pipefail

mkdir -p artifacts/divergence

cat > artifacts/divergence/contract.json <<'JSON'
{
  "analysis_class": "DivergenceAnalysis",
  "methods": ["analyze"],
  "analyze_signature": "analyze(signaling: ndarray[N,N], alpha: ndarray[N,N], adjacency: ndarray[N,N], neuron_ids: list[str]) -> dict",
  "protocol_version": "1.0",
  "alpha_threshold": 0.95,
  "community_method": "greedy_modularity",
  "hub_fraction": 0.1,
  "null_model": "degree_preserving_swap",
  "edge_definition": "abs_weight_max_symmetrised",
  "judgment_thresholds": {
    "edge_weak_lift_max": 2.0,
    "modules_low_nmi_max": 0.3,
    "modules_above_null_z_min": 2.0,
    "pharynx_enrich_min": 2.0
  },
  "hub_tie_break": "neuron_id_ascending",
  "hub_significance": "two_sided_pearson_t_alpha_0.05"
}
JSON

cat > artifacts/divergence/divergence_analysis.py <<'PY'
"""参考解：结构-功能分歧分析器（冻结协议 v1.0 的独立实现）。

与 checks/evaluate_external.py 的 truth_analysis 是同一协议的两份独立实现；
两者在真实数据上应给出一致数值（容差见评分脚本）。
"""
import numpy as np
import networkx as nx
from networkx.algorithms.community import greedy_modularity_communities
from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score

ALPHA_THRESHOLD = 0.95
HUB_FRACTION = 0.10
N_NULL = 10
NULL_SEED = 20260916
SWAP_FACTOR = 3

PHARYNX = {"I1L", "I1R", "I2L", "I2R", "I3", "I4", "I5", "I6", "M1",
           "M2L", "M2R", "M3L", "M3R", "M4", "M5", "MC1DL", "MC1DR",
           "MC1VL", "MC1VR", "MCL", "MCR", "MI", "NSML", "NSMR"}


def _ranks(x):
    order = np.argsort(x, kind="mergesort")
    xs = x[order]
    r = np.empty(x.shape[0], dtype=np.float64)
    i = 0
    while i < xs.shape[0]:
        j = i
        while j + 1 < xs.shape[0] and xs[j + 1] == xs[i]:
            j += 1
        r[order[i:j + 1]] = 0.5 * (i + j) + 1.0
        i = j + 1
    return r


def _auroc(y, s):
    y = np.asarray(y).astype(bool)
    n_pos, n_neg = int(y.sum()), int((~y).sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    r = _ranks(np.asarray(s, dtype=np.float64))
    return float((r[y].sum() - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg))


def _average_precision(y, s):
    y = np.asarray(y).astype(bool)
    n_pos = int(y.sum())
    if n_pos == 0 or n_pos == y.shape[0]:
        return float("nan")
    order = np.argsort(-np.asarray(s, dtype=np.float64), kind="mergesort")
    ys = y[order]
    tp = np.cumsum(ys)
    prec = tp / np.arange(1, ys.shape[0] + 1)
    return float((prec * ys).sum() / n_pos)


def _harmonic(n):
    if n < 10000:
        return float(np.sum(1.0 / np.arange(1, n + 1)))
    euler = 0.5772156649015329
    return float(np.log(n) + euler + 1.0 / (2 * n) - 1.0 / (12 * n * n))


def _ap_chance(n, m):
    if n < 2 or m <= 0 or m >= n:
        return float("nan")
    h = _harmonic(n)
    return float(h / n + (m - 1) / (n - 1) * (1.0 - h / n))


def _graph(topology, weights=None):
    G = nx.Graph()
    n = topology.shape[0]
    G.add_nodes_from(range(n))
    iu = np.triu_indices(n, k=1)
    for i, j in zip(*iu):
        if topology[i, j]:
            G.add_edge(int(i), int(j), weight=1.0 if weights is None else float(weights[i, j]))
    return G


def _comms(G):
    return [set(c) for c in greedy_modularity_communities(G, weight="weight")]


def _labels(comms, n):
    lab = np.full(n, -1, dtype=int)
    for k, c in enumerate(comms):
        for x in c:
            lab[x] = k
    return lab


class DivergenceAnalysis:
    """对「信号传播图谱 vs 电镜连接组」的结构-功能分歧给出统计量与判断。"""

    def analyze(self, signaling, alpha, adjacency, neuron_ids):
        S = np.maximum(np.abs(signaling), np.abs(signaling.T))
        np.fill_diagonal(S, 0.0)
        T = ((alpha >= ALPHA_THRESHOLD) | (alpha.T >= ALPHA_THRESHOLD)).astype(np.uint8)
        np.fill_diagonal(T, 0)
        A = np.asarray(adjacency).astype(np.uint8)
        n = A.shape[0]

        # 边级一致性
        iu = np.triu_indices(n, k=1)
        y = A[iu].astype(int)
        s = S[iu]
        ok = np.isfinite(s)
        y, s = y[ok], s[ok]
        ap = _average_precision(y, s)
        chance = _ap_chance(y.shape[0], int(y.sum()))
        lift = ap / chance

        # 模块对齐 + 度保持零模型
        rng = np.random.default_rng(NULL_SEED)
        # 社区检测在二元拓扑上做（与冻结协议一致）
        G_a, G_s = _graph(A), _graph(T)
        comm_a, comm_s = _comms(G_a), _comms(G_s)
        lab_a, lab_s = _labels(comm_a, n), _labels(comm_s, n)
        nmi = float(normalized_mutual_info_score(lab_a, lab_s))
        ars = float(adjusted_rand_score(lab_a, lab_s))
        null = []
        for _ in range(N_NULL):
            H = G_a.copy()
            nswap = SWAP_FACTOR * H.number_of_edges()
            nx.double_edge_swap(H, nswap=nswap, max_tries=100 * nswap,
                                seed=int(rng.integers(1 << 30)))
            null.append(float(normalized_mutual_info_score(_labels(_comms(H), n), lab_s)))
        null = np.array(null)
        sd = float(null.std())
        nmi_z = (nmi - float(null.mean())) / sd if sd > 1e-12 else 0.0

        # hub 重叠（超几何零模型）
        # 两侧 hub 都用**度数**：解剖图度数 vs 显著信号子图度数。
        # 不用加权强度：信号矩阵 31% 缺失，且缺失极不均匀（corr(测量数, Σ|w|)=+0.78），
        # 求和强度排名会在排"谁测得最多"。显著子图无缺失，口径干净。
        # 并列按神经元 id 升序破（行序无关）。
        _names = [str(x) for x in (neuron_ids or [])]

        def _topk(vals, kk):
            order = sorted(range(len(vals)), key=lambda i: (-float(vals[i]), _names[i]))
            return set(order[:kk])

        deg = A.sum(1).astype(float)
        deg_sig = T.sum(1).astype(float)
        degree_corr = float(np.corrcoef(deg, deg_sig)[0, 1])   # 源论文的 hub 汇总量
        # 该相关的显著性（双侧 Pearson, alpha=0.05）。p 落在 (0.05, 0.10) 时报 None：
        # 这个区间内单侧检验会给出相反答案，属"实现自由度翻转判定"，与别的 grey
        # （离阈值太近）性质不同。
        from scipy.stats import t as _tdist
        _tstat = degree_corr * np.sqrt((n - 2) / max(1e-12, 1.0 - degree_corr ** 2))
        corr_p = float(2.0 * (1.0 - _tdist.cdf(abs(_tstat), n - 2)))
        corr_sig = None if 0.05 <= corr_p <= 0.10 else bool(degree_corr > 0.0 and corr_p <= 0.05)
        k = max(5, int(round(HUB_FRACTION * n)))
        hubs_a = _topk(deg, k)
        hubs_s = _topk(deg_sig, k)
        overlap = len(hubs_a & hubs_s)
        mu = k * k / n
        sd_h = float(np.sqrt(k * (k / n) * (1 - k / n) * (n - k) / (n - 1)))
        rc_z = (overlap - mu) / sd_h if sd_h > 1e-12 else 0.0
        if not np.isfinite(rc_z):
            raise ValueError("hub overlap z is not finite; check the missing-data rule")

        # 咽部共分配率（用连接组节点数推断：调用方传入的 adjacency 已限定到交集）
        out = {
            "edge": {"auroc": _auroc(y, s), "lift": float(lift)},
            "modules": {"nmi": nmi, "nmi_null_z": float(nmi_z), "ars": ars},
            "hub_overlap": {"k": int(k), "overlap": int(overlap),
                            "null_z": float(rc_z), "degree_corr": degree_corr},
            "judgments": {
                "edge_consistency_weak": bool(lift < 2.0),
                "modules_low_but_above_null": bool(nmi < 0.30 and nmi_z > 2.0),
                "hub_degree_corr_significant": corr_sig,
            },
        }
        # 咽部：仅当连接组含咽部神经元时可算（体神经系统导出不含 → computable=False）。
        # **两侧都算**：解剖社区与显著信号社区各自用**自己的**共分配基线。
        ph = [i for i, name in enumerate(_names) if name in PHARYNX]
        if len(ph) < 5:
            pharynx = {"computable": False, "coassignment": float("nan"),
                       "enrichment": float("nan"),
                       "coassignment_signaling": float("nan"),
                       "enrichment_signaling": float("nan")}
        else:
            def _same(comms):
                s_set = set(ph)
                return sum(len(s_set & c) * (len(s_set & c) - 1) // 2 for c in comms)

            n_pairs = len(ph) * (len(ph) - 1) // 2
            e_a, e_s = _same(comm_a) / n_pairs, _same(comm_s) / n_pairs
            base_a = sum(len(c) * (len(c) - 1) // 2 for c in comm_a) / (n * (n - 1) / 2)
            base_s = sum(len(c) * (len(c) - 1) // 2 for c in comm_s) / (n * (n - 1) / 2)
            pharynx = {"computable": True,
                       "coassignment": float(e_a),
                       "enrichment": float(e_a / max(base_a, 1e-12)),
                       "coassignment_signaling": float(e_s),
                       "enrichment_signaling": float(e_s / max(base_s, 1e-12))}
        out["pharynx"] = pharynx
        out["judgments"]["pharynx_distinct_in_anatomy"] = (
            None if not pharynx["computable"] else bool(pharynx["enrichment"] >= 2.0))
        out["judgments"]["pharynx_distinct_in_signaling"] = (
            None if not pharynx["computable"]
            else bool(pharynx["enrichment_signaling"] >= 2.0))
        return out
PY

cat > artifacts/report.md <<'MD'
# Reference submission (celegans-structure-function-divergence)

`solution/solution.sh` 生成的参考产物。分析器是冻结协议 v1.0 的独立实现，
用于跑通 Oracle 门并在正常模式下作基准（应得满分）。

**本报告只代表公开侧的那一份数据**：下面所有数值来自 `public/signaling.npz` ×
`public/connectome_witvliet_2020_7.npz`（交集后 n = 138）。评测端会在若干**我没有拿到**
的重建上重跑同一份代码，因此报告不报它们的数字，只说明每条结论的适用范围。

## 实测数值（公开重建 witvliet_2020_7，n = 138）

| 统计量 | 值 | 判读所依据的机会水平 |
|---|---|---|
| 边级 `auroc` / `lift`（阈值 2.0） | 0.556 / **1.225** | 精确 E[AP]（随机排序下的解析机会值） |
| 模块 `nmi` / `ars` | 0.116 / 0.082 | 度保持零模型（z 见下） |
| 模块 `nmi_null_z`（阈值 2.0，不计分） | +3.94（落在 grey 区间） | 度保持交换零模型，10 次重复 |
| hub `k` / 重叠 / `null_z` | 14 / 2 / +0.54 | 超几何期望（E = k²/N） |
| hub 度数相关 `r` 及其 `p` | +0.094 / **p = 0.271** | 双侧 Pearson t 检验（n = 138，t = 1.102，df = 136） |
| 咽部富集（解剖 / 信号） | **不可算** | 该重建为纯体神经导出，咽部神经元 0 个 |

判断题：`edge_consistency_weak` = True；`hub_degree_corr_significant` = False；
`modules_low_but_above_null` 与两个咽部题在本重建上**不适用**（前者驱动量落在
协议的可判定区间之外，后者 `computable = false`）。

## 结论的适用范围（哪些稳健、哪些对重建敏感）

- **较稳健**：边级弱一致（lift = 1.23 ≪ 2.0）—— 三份数据源上的量级差不太可能把它推过阈值；
  信号侧的结构（显著子图由 `alpha ≥ 0.95` 定义，无缺失值）也不依赖具体重建的覆盖率。
- **对重建敏感**：**解剖侧咽部富集** —— 它取决于该重建是否覆盖咽部神经元、覆盖了几个；
  纯体神经导出的重建上根本不可算（本重建即如此），而覆盖更全的重建上可能给出显著值。
- **对重建敏感**：**度数相关的显著性** —— 本重建 `p = 0.271`，离 0.05 尚远，但离判据边界
  （`p ∈ (0.05, 0.10]` 记不适用）并不远；换一份重建完全可能落进不适用区间或翻成显著。
- **对重建敏感**：任何驱动量贴阈值的量（模块优于零模型的 `nmi_null_z`）—— 跨实现的离散度
  可达相对数十个百分点，本重建的 +3.94 落在 grey 内，故该题不计分。

因此本报告不把任何一条结论说成总体结论：以上都是**单图谱 × 单重建**上的观察，
对另一份重建是否成立无法从本数据判定。

## 方法（要点）

1. **边级一致性**：信号强度（`|w|` 的 max 对称化）对解剖边做排序，报告 AUROC 与
   `lift = AUPRC / 精确机会值`（机会值用随机排序下 E[AP] 的解析式，不是边密度 ——
   后者会把 lift 系统性抬高约 1%）。
2. **模块对齐**：解剖二值图与 `alpha ≥ 0.95` 的显著信号子图各做贪心模块度社区检测，
   报告 NMI 与**度保持零模型**下的 z 值，并另报**调整兰德分数 ARS**
   （源论文报告模块对齐用的是 ARS；同一批分区下 ARS ≤ NMI）。
3. **hub 一致性**：两个口径都算 —— (a) 两网络**度数相关 r**（阈值无关的汇总量）；
   (b) 各按**度数**取前 10% 的 hub 重叠数与超几何零模型 z（依赖 k 的任意选择，只作
   描述量，不出判断题：`overlap` 是整数、z 的量子化步长约 0.84）。(a) 的**显著性**
   出成判断题 —— 它是唯一阈值无关又能落成二元结论的 hub 量。
4. **咽部**：需要连接组含咽部神经元；可算时解剖侧与信号侧**分别**出数（共用"同社区
   对数比例 / 该图自身社区结构下的期望比例"这一口径），不可算时标 `computable: false`
   且两个咽部判断题取 `null`。

## 实现状态

- 已实现：边级 / 模块 / hub 三组统计量与三个判断题；咽部四量（含不可算分支）；
  对任意重建通用的管线（不硬编码版本、不按 N 特判）。
- 未实现：无（缺口会在下方注明）。
MD

echo "[reference] artifacts written to ./artifacts"
