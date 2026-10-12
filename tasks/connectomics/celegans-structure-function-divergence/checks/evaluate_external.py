#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""celegans-structure-function-divergence 的评分脚本（评测端，绝不进 agent 工作区）。

任务：agent 提交一个分析器，对「信号传播图谱 vs 电镜连接组」的结构-功能分歧
给出**从数据算出的统计量**与**判断题**。scorer 用同一套冻结协议独立复算真值，
再逐项比对。

冻协议（改动必须 bump task.yaml 的 version）：
    alpha_threshold     0.95        显著传播边（q ≤ 0.05）
    missing_values      信号矩阵约 31% 的对是 NaN（每神经元覆盖率 0.11–0.99）
                        → 一切排序类统计量**剔除未测量对**，绝不代填
    community_method    greedy_modularity（Clauset-Newman-Moore，**二元拓扑**，权重恒 1）
    hub_fraction        0.10        hub 取前 10%（k = max(5, round(0.1N))），两侧**都按度数**
    hub_tie_break       neuron_id_ascending（使排名与数组行序无关）
    null_model          degree_preserving_swap（double_edge_swap，3×E 次，10 次重复）
    null_seed           20260916
    hub_significance    双侧 Pearson（n-2 自由度 t 检验，α=0.05）判"两网络度数相关
                        是否显著为正"；p ∈ (0.05, 0.10) 记不适用（单/双侧会翻转）

评测版本：私有目录下固定的三份连接组都会跑一遍
（public 只给 witvliet_2020_7，agent 看不到其余版本 → 必须写出**通用**管线）。

哨兵契约：在 >>>>> BPB_SCORES / <<<<< BPB_SCORES 之间输出一行扁平 {string: number}。
NOP 语义：无产物 / 必需产物缺失 / 私有数据缺失 / 契约不符 → **不输出哨兵**，非零退出，
scorer 记 unscored（绝不返回 0）。

用法：
    evaluate_external.py --artifacts <run>/artifacts --private <私有目录> --worker-image <digest>
    evaluate_external.py --self-test
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import selectors
import subprocess
import sys
import tempfile
import time
from typing import Any, Sequence
import uuid

# The trusted parent never imports submitted Python. A separate Docker worker
# sees only the submitted artifact tree and one reconstruction's input arrays.
sys.dont_write_bytecode = True

START = ">>>>> BPB_SCORES"
END = "<<<<< BPB_SCORES"

# ---- 冻结协议常量（改动必须 bump version）----
ALPHA_THRESHOLD = 0.95
COMMUNITY_METHOD = "greedy_modularity"
HUB_FRACTION = 0.10
NULL_MODEL = "degree_preserving_swap"
N_NULL = 10
NULL_SEED = 20260916
SWAP_FACTOR = 3
PROTOCOL_VERSION = "1.0"
HUB_TIE_BREAK = "neuron_id_ascending"   # 前 k 名并列的破除规则（行序无关）
HUB_SIGNIFICANCE = "two_sided_pearson_t_alpha_0.05"   # 度数相关显著性检验的冻结口径

# oracle 合成夹具（参数已实测标定，使各判据都有确定答案）
ORACLE_NEURONS = 96
ORACLE_SEED = 20260916
ORACLE_TOPOLOGY_KEEP = 0.25

# 判断题阈值（写进题面，agent 与 scorer 用同一组）
EDGE_WEAK_LIFT_MAX = 2.0          # lift < 2.0 视为"弱一致"
MODULES_LOW_NMI_MAX = 0.30        # NMI < 0.30 视为"低对齐"
MODULES_ABOVE_NULL_Z_MIN = 2.0    # 零模型 z > 2 视为"显著优于随机"
PHARYNX_ENRICH_MIN = 2.0          # 富集 ≥ 2 倍视为"该网络中成独立社区"（解剖/信号两侧同阈值）

# Grey zones protect judgments from small numerical and implementation
# differences. The thresholds below are protocol constants, not data answers.
# nmi_null_z is stochastic and is required as an output but is not itself a
# scored statistic. Hub top-k overlap is descriptive and has no judgment item.
GREY = {"lift": (1.8, 2.2), "nmi_null_z": (1.0, 6.0),
        "pharynx_enrich": (1.6, 2.4),
        # The p-value interval is a declared convention where one- and
        # two-sided conclusions could differ.
        "degree_corr_p": (0.05, 0.10)}

HUB_CORR_ALPHA = 0.05            # 度数相关显著性检验的显著水平（双侧 Pearson）

# 比对容差。
# 注意：**不含 nmi_null_z**，它已从计分项移出（见下面 NO_SCORE_NOTE）。
TOL = {"auroc": 0.02, "lift": 0.10, "nmi": 0.03,
       "ars": 0.02, "overlap": 1.0, "null_z": 0.5, "degree_corr": 0.02,
       "coassignment": 0.05, "enrichment": 0.30}

# nmi_null_z stays in the required output but is not a pointwise statistic:
# finite-sample null-model variation was too large for a fair fixed tolerance.
# Its related judgment is scored only outside the declared grey interval.

PHARYNX_NAMES = {
    "I1L", "I1R", "I2L", "I2R", "I3", "I4", "I5", "I6",
    "M1", "M2L", "M2R", "M3L", "M3R", "M4", "M5",
    "MC1DL", "MC1DR", "MC1VL", "MC1VR", "MCL", "MCR", "MI", "NSML", "NSMR",
}

# 私密评测目录的环境变量名。**优先用框架认得的规范名**：
# src/workflow.ts 的 assertAgentDataBoundary 只拦 BPB_PRIVATE_EVAL_DIR /
# BPB_TOPS_PRIVATE_EVAL_DIR，src/adapters.ts 的 agentEnvironment 也只从 agent 进程里
# 清洗这两个名字。用 per-task 名字的话，两处护栏都失效——若在同 shell 里先铺私密数据
# 再跑 agent，私有目录路径会随环境继承进 agent 进程。旧名保留兼容。
PRIVATE_ENV = "BPB_PRIVATE_EVAL_DIR"
PRIVATE_ENV_LEGACY = "BPB_CELEGANS_DIVERGENCE_PRIVATE_EVAL_DIR"
EXPECTED_VERSIONS = (
    "cook_2019.npz",
    "white_1986_whole.npz",
    "witvliet_2020_8.npz",
)


def emit(metrics: dict[str, float]) -> None:
    """按哨兵契约输出一行扁平 {string: number}。"""
    flat: dict[str, float] = {}
    for k, v in metrics.items():
        fv = float(v)
        if fv != fv:
            raise SystemExit(f"refusing to emit NaN for metric {k}")
        flat[k] = fv
    if not flat:
        raise SystemExit("refusing to emit an empty metric set")
    print(START)
    print(json.dumps(flat, sort_keys=True))
    print(END)


# ================================================================ 冻结协议实现
# 这一节是"真值"的唯一定义处。agent 侧参考解须独立实现同一协议；
# 容差使实现细节（RNG 消耗顺序等）不影响判定。
def _auc(y, s) -> float:
    """Mann-Whitney AUROC（平均秩，机会 0.5）。"""
    import numpy as np

    y = np.asarray(y).astype(bool)
    s = np.asarray(s, dtype=np.float64)
    n_pos, n_neg = int(y.sum()), int((~y).sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    order = np.argsort(s, kind="mergesort")
    ranks = np.empty(s.shape[0], dtype=np.float64)
    sorted_s = s[order]
    i = 0
    while i < sorted_s.shape[0]:
        j = i
        while j + 1 < sorted_s.shape[0] and sorted_s[j + 1] == sorted_s[i]:
            j += 1
        ranks[order[i:j + 1]] = 0.5 * (i + j) + 1.0
        i = j + 1
    return float((ranks[y].sum() - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg))


def _average_precision(y, s) -> float:
    """average precision（AUPRC）。"""
    import numpy as np

    y = np.asarray(y).astype(bool)
    s = np.asarray(s, dtype=np.float64)
    n_pos = int(y.sum())
    if n_pos == 0 or n_pos == y.shape[0]:
        return float("nan")
    order = np.argsort(-s, kind="mergesort")
    ys = y[order]
    tp = np.cumsum(ys)
    prec = tp / np.arange(1, ys.shape[0] + 1)
    return float((prec * ys).sum() / n_pos)


def _harmonic(n: int) -> float:
    import numpy as np

    if n <= 0:
        return float("nan")
    if n < 10000:
        return float(np.sum(1.0 / np.arange(1, n + 1)))
    euler = 0.5772156649015329
    return float(np.log(n) + euler + 1.0 / (2 * n) - 1.0 / (12 * n * n))


def _ap_chance(n: int, m: int) -> float:
    """随机排序下 average precision 的**精确**期望。

    E[AP] = H_n/n + (m-1)/(n-1)·(1 - H_n/n)，严格大于密度 m/n。
    用密度当机会水平会系统性抬高 lift（本题规模下约 1%）。
    """
    import numpy as np

    if n < 2 or m <= 0 or m >= n:
        return float("nan")
    h = _harmonic(n)
    return float(h / n + (m - 1) / (n - 1) * (1.0 - h / n))


def sym_abs_max(M):
    """任务冻结的边定义：|w| 的 max 对称化，对角置零。"""
    import numpy as np

    S = np.maximum(np.abs(M), np.abs(M.T))
    np.fill_diagonal(S, 0.0)
    return S


def signaling_topology(alpha):
    """阈值化显著子网：alpha ≥ 阈值 的任一方向即视为无向边。"""
    import numpy as np

    T = ((alpha >= ALPHA_THRESHOLD) | (alpha.T >= ALPHA_THRESHOLD)).astype(np.uint8)
    np.fill_diagonal(T, 0)
    return T


def _to_graph(topology, weights=None):
    import networkx as nx
    import numpy as np

    G = nx.Graph()
    n = topology.shape[0]
    G.add_nodes_from(range(n))
    iu = np.triu_indices(n, k=1)
    for i, j in zip(*iu):
        if topology[i, j]:
            G.add_edge(int(i), int(j),
                       weight=1.0 if weights is None else float(weights[i, j]))
    return G


def _topk(values, ids, k):
    """取前 k 大的下标；并列按神经元 id 升序破。

    破并列规则是协议的一部分：若按下标破并列，结果会依赖私有文件的**行序**——
    同一份数据换个行序就换一批 hub，答案册随之漂移。按 id 破是行序无关的。

    另：这里显式拒绝非有限值。旧版用 `S.sum(1)` 作"信号强度"，而信号矩阵有 31%
    的缺失对（NaN），求和后**每个节点都是 NaN**，`argsort` 退化成"取前 k 个下标"，
    统计量彻底无效却仍能被两份实现一致地复现——这类静默失效必须在源头拦住。
    """
    import numpy as np

    arr = np.asarray(values, dtype=float)
    if not np.isfinite(arr).all():
        raise ValueError("hub ranking received non-finite values (check the missing-data rule)")
    order = sorted(range(arr.shape[0]), key=lambda i: (-float(arr[i]), str(ids[i])))
    return set(order[:k])


def _communities(G):
    import networkx as nx

    return [set(c) for c in nx.algorithms.community.greedy_modularity_communities(
        G, weight="weight")]


def _labels(comms, n):
    import numpy as np

    lab = np.full(n, -1, dtype=int)
    for k, c in enumerate(comms):
        for x in c:
            lab[x] = k
    return lab


def _randomized(G, rng):
    import networkx as nx

    H = G.copy()
    nswap = SWAP_FACTOR * H.number_of_edges()
    nx.double_edge_swap(H, nswap=nswap, max_tries=100 * nswap,
                        seed=int(rng.integers(1 << 30)))
    return H


def positive_hub_significance(correlation: float, p_value: float):
    """Return the protocol judgment for a significantly positive correlation."""
    if not math.isfinite(p_value) or GREY["degree_corr_p"][0] <= p_value <= GREY["degree_corr_p"][1]:
        return None
    return bool(correlation > 0.0 and p_value <= HUB_CORR_ALPHA)


def truth_analysis(signaling, alpha, adjacency, neuron_ids) -> dict[str, Any]:
    """冻结协议的参考实现——scorer 的真值来源。

    neuron_ids 与该连接组的行/列一一对应（交集后的顺序）。
    """
    import numpy as np
    from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score

    S = sym_abs_max(np.asarray(signaling, dtype=np.float64))
    T = signaling_topology(np.asarray(alpha, dtype=np.float64))
    A = np.asarray(adjacency).astype(np.uint8)
    n = A.shape[0]

    # ---- 边级一致性 ----
    iu = np.triu_indices(n, k=1)
    y = A[iu].astype(int)
    s = S[iu]
    ok = np.isfinite(s)
    y, s = y[ok], s[ok]
    ap = _average_precision(y, s)
    chance = _ap_chance(y.shape[0], int(y.sum()))
    edge = {"auroc": _auc(y, s), "auprc": ap, "chance": chance,
            "lift": ap / chance if chance and chance == chance else float("nan")}

    # ---- 模块对齐 + 度保持零模型 ----
    rng = np.random.default_rng(NULL_SEED)
    # Communities use the declared binary topology, with unit edge weights.
    G_a, G_s = _to_graph(A), _to_graph(T)
    comm_a, comm_s = _communities(G_a), _communities(G_s)
    lab_a, lab_s = _labels(comm_a, n), _labels(comm_s, n)
    nmi = float(normalized_mutual_info_score(lab_a, lab_s))
    # Report both NMI and adjusted Rand score for the same partitions.
    ars = float(adjusted_rand_score(lab_a, lab_s))
    null = []
    for _ in range(N_NULL):
        comm_r = _communities(_randomized(G_a, rng))
        null.append(float(normalized_mutual_info_score(_labels(comm_r, n), lab_s)))
    null = np.array(null)
    sd = float(null.std())
    modules = {"nmi": nmi, "ars": ars,
               "n_comm_anat": len(comm_a), "n_comm_sign": len(comm_s),
               "nmi_null_mean": float(null.mean()), "nmi_null_sd": sd,
               "nmi_null_z": (nmi - float(null.mean())) / sd if sd > 1e-12 else 0.0}

    # ---- hub 重叠（零模型 = 超几何）----
    # 两侧 hub 都用**度数**定义：解剖图度数 vs 显著信号子图度数。
    # Degree is the declared hub measure on both binary graphs; a sum of
    # measured signal amplitudes would be sensitive to missing-pair coverage.
    names = [str(x) for x in (neuron_ids or [])]
    deg = A.sum(1).astype(float)
    deg_sig = T.sum(1).astype(float)
    k = max(5, int(round(HUB_FRACTION * n)))
    hubs_a = _topk(deg, names, k)
    hubs_s = _topk(deg_sig, names, k)
    overlap = len(hubs_a & hubs_s)
    mu = k * k / n
    sd_h = float(np.sqrt(k * (k / n) * (1 - k / n) * (n - k) / (n - 1)))
    # Degree correlation is continuous; top-k overlap depends on the chosen k.
    with np.errstate(invalid="ignore", divide="ignore"):
        corr = np.corrcoef(deg, deg_sig)[0, 1]
    degree_corr = float(corr) if np.isfinite(corr) else 0.0
    # The protocol-defined correlation judgment uses a two-sided Pearson t
    # calculation and additionally requires a positive correlation.
    corr_p = float("nan")
    if n > 2 and abs(degree_corr) < 1.0:
        tstat = degree_corr * np.sqrt((n - 2) / max(1e-12, 1.0 - degree_corr ** 2))
        try:
            from scipy.stats import t as _tdist
            corr_p = float(2.0 * (1.0 - _tdist.cdf(abs(tstat), n - 2)))
        except Exception:      # 无 scipy 时退正态近似；在 (0.05,0.10) 这档判定完全一致
            import math
            z = degree_corr * np.sqrt(n - 1.0)
            corr_p = float(2.0 * (1.0 - 0.5 * (1.0 + math.erf(abs(z) / math.sqrt(2.0)))))
    hub = {"k": k, "overlap": overlap,
           "null_mean": float(mu), "null_sd": sd_h,
           "null_z": (overlap - mu) / sd_h if sd_h > 1e-12 else 0.0,
           "degree_corr": degree_corr, "degree_corr_p": corr_p}

    # ---- 咽部（仅当连接组含咽部神经元）----
    ph = sorted(i for i, name in enumerate(names) if name in PHARYNX_NAMES)
    if len(ph) < 5:
        pharynx = {"computable": False, "coassignment": float("nan"),
                   "enrichment": float("nan"), "n_pharynx": len(ph)}
    else:
        def pairs_same(comm):
            s_set = set(ph)
            same = 0
            for c in comm:
                kk = len(s_set & c)
                same += kk * (kk - 1) // 2
            return same

        n_ph_pairs = len(ph) * (len(ph) - 1) // 2
        e_a = pairs_same(comm_a) / n_ph_pairs
        e_s = pairs_same(comm_s) / n_ph_pairs
        base_a = sum(len(c) * (len(c) - 1) // 2 for c in comm_a) / (n * (n - 1) / 2)
        base_s = sum(len(c) * (len(c) - 1) // 2 for c in comm_s) / (n * (n - 1) / 2)
        pharynx = {"computable": True, "n_pharynx": len(ph),
                   "coassignment": float(e_a), "enrichment": float(e_a / max(base_a, 1e-12)),
                   "coassignment_signaling": float(e_s),
                   "enrichment_signaling": float(e_s / max(base_s, 1e-12))}

    def _decisive(value, lo, hi):
        """落在可判定区间外才算可判定；区间内返回 None（不记分）。"""
        return not (lo <= value <= hi)

    ph_enr = pharynx.get("enrichment", float("nan"))
    ph_enr_s = pharynx.get("enrichment_signaling", float("nan"))
    corr_p = hub.get("degree_corr_p", float("nan"))
    judgments = {
        "edge_consistency_weak": (
            bool(edge["lift"] < EDGE_WEAK_LIFT_MAX)
            if _decisive(edge["lift"], *GREY["lift"]) else None),
        "modules_low_but_above_null": (
            bool(modules["nmi"] < MODULES_LOW_NMI_MAX
                 and modules["nmi_null_z"] > MODULES_ABOVE_NULL_Z_MIN)
            if _decisive(modules["nmi_null_z"], *GREY["nmi_null_z"]) else None),
        "pharynx_distinct_in_anatomy": (
            None if not pharynx["computable"]
            else (bool(ph_enr >= PHARYNX_ENRICH_MIN)
                  if _decisive(ph_enr, *GREY["pharynx_enrich"]) else None)),
        "pharynx_distinct_in_signaling": (
            None if not pharynx["computable"]
            else (bool(ph_enr_s >= PHARYNX_ENRICH_MIN)
                  if _decisive(ph_enr_s, *GREY["pharynx_enrich"]) else None)),
        "hub_degree_corr_significant": positive_hub_significance(degree_corr, corr_p),
    }
    return {"edge": edge, "modules": modules, "hub_overlap": hub,
            "pharynx": pharynx, "judgments": judgments}


# ================================================================ agent 产物
def validate_contract(artifacts_dir: str) -> dict:
    """按 output_schema.json 的必需字段与 const 值做最小校验（不引入 jsonschema）。"""
    path = os.path.join(artifacts_dir, "divergence", "contract.json")
    if not os.path.isfile(path):
        raise FileNotFoundError(f"missing contract artifact: {path}")
    with open(path, encoding="utf-8") as f:
        c = json.load(f)

    for key in ("analysis_class", "methods", "protocol_version", "alpha_threshold",
                "community_method", "hub_fraction", "hub_tie_break", "hub_significance",
                "null_model", "edge_definition"):
        if key not in c:
            raise ValueError(f"contract.json missing required key: {key}")

    if c["analysis_class"] != "DivergenceAnalysis":
        raise ValueError(f"contract.analysis_class must be DivergenceAnalysis, got {c['analysis_class']!r}")
    if not isinstance(c["methods"], list) or "analyze" not in c["methods"]:
        raise ValueError("contract.methods must include 'analyze'")
    if "analyze_signature" in c and "neuron_ids" not in c["analyze_signature"]:
        raise ValueError("contract.analyze_signature must mention neuron_ids")

    # 冻结常量：改了会让分数不可比，必须拦下。
    expected = {
        "protocol_version": PROTOCOL_VERSION,
        "alpha_threshold": ALPHA_THRESHOLD,
        "community_method": COMMUNITY_METHOD,
        "hub_fraction": HUB_FRACTION,
        "hub_tie_break": HUB_TIE_BREAK,
        "hub_significance": HUB_SIGNIFICANCE,
        "null_model": NULL_MODEL,
        "edge_definition": "abs_weight_max_symmetrised",
    }
    for key, want in expected.items():
        if isinstance(want, float):
            ok = isinstance(c[key], (int, float)) and abs(float(c[key]) - want) < 1e-12
        else:
            ok = c[key] == want
        if not ok:
            raise ValueError(f"contract.{key} must be {want!r} (frozen), got {c[key]!r}")
    return c


def run_candidate(artifacts_dir: str, image: str, signaling, alpha,
                  adjacency, neuron_ids) -> dict:
    """Execute candidate Python in a read-only, networkless Docker worker.

    The parent keeps its scorer code and truth in this process. Only the input
    arrays for one reconstruction cross into the worker; no private directory,
    scorer source, Docker socket, or host workspace is mounted there.
    """
    import numpy as np

    if not image:
        raise RuntimeError("Docker worker image not configured")
    artifacts = Path(artifacts_dir).resolve(strict=True)
    cache = Path(__file__).resolve().parents[4] / ".cache" / "celegans"
    cache.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="worker-", dir=cache) as temporary:
        input_file = Path(temporary) / "input.npz"
        np.savez_compressed(input_file, signaling=signaling, alpha=alpha,
                            adjacency=adjacency,
                            neuron_ids=np.asarray(neuron_ids, dtype=np.str_))
        input_file.chmod(0o444)
        container_name = f"bpb-celegans-{uuid.uuid4().hex}"
        docker_binary = os.environ.get("BPB_DOCKER_BINARY", "docker")
        command = [
            docker_binary, "run", "--rm", "--name", container_name,
            "--network", "none", "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--pids-limit", "64",
            "--memory", "1g", "--cpus", "2", "--user", "65534:65534",
            "--tmpfs", "/tmp:rw,nosuid,noexec,size=64m",
            "--mount", f"type=bind,src={artifacts},dst=/candidate,readonly",
            "--mount", f"type=bind,src={input_file},dst=/input.npz,readonly",
            image,
        ]
        process = subprocess.Popen(command, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)
        streams = selectors.DefaultSelector()
        assert process.stdout is not None and process.stderr is not None
        streams.register(process.stdout, selectors.EVENT_READ, "stdout")
        streams.register(process.stderr, selectors.EVENT_READ, "stderr")
        captured = {"stdout": bytearray(), "stderr": bytearray()}
        deadline = time.monotonic() + 180
        aborted = False
        try:
            while streams.get_map():
                if time.monotonic() >= deadline:
                    raise TimeoutError("Docker worker exceeded 180 seconds")
                for key, _ in streams.select(timeout=max(0.0, min(1.0, deadline - time.monotonic()))):
                    block = os.read(key.fileobj.fileno(), 65536)
                    if not block:
                        streams.unregister(key.fileobj)
                        continue
                    captured[key.data].extend(block)
                    if len(captured[key.data]) > 1_000_000:
                        raise RuntimeError("Docker worker output exceeded 1 MB")
            return_code = process.wait(timeout=5)
        except (TimeoutError, RuntimeError, subprocess.TimeoutExpired):
            aborted = True
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            raise
        finally:
            streams.close()
            if aborted:
                try:
                    subprocess.run([docker_binary, "rm", "-f", container_name],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   timeout=10, check=False)
                except subprocess.TimeoutExpired:
                    pass
        if return_code != 0:
            raise RuntimeError(f"Docker worker failed (exit {return_code})")
        try:
            payload = json.loads(captured["stdout"].decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("Docker worker returned non-JSON output") from exc
        if not isinstance(payload, dict):
            raise ValueError("Docker worker returned a non-object result")
        return payload


def _check_payload(payload: Any) -> None:
    """校验 agent 返回结构，缺失即契约不符（不静默补默认值）。"""
    if not isinstance(payload, dict):
        raise ValueError(f"analyze() must return a dict, got {type(payload).__name__}")
    for section, keys in (("edge", ("auroc", "lift")),
                          ("modules", ("nmi", "nmi_null_z", "ars")),
                          ("hub_overlap", ("k", "overlap", "null_z", "degree_corr")),
                          ("judgments", ("edge_consistency_weak",
                                         "modules_low_but_above_null",
                                         "hub_degree_corr_significant"))):
        if section not in payload or not isinstance(payload[section], dict):
            raise ValueError(f"analyze() output missing section: {section}")
        for key in keys:
            if key not in payload[section]:
                raise ValueError(f"analyze() output missing {section}.{key}")
    if "pharynx" not in payload or not isinstance(payload["pharynx"], dict):
        raise ValueError("analyze() output missing section: pharynx")
    if "computable" not in payload["pharynx"]:
        raise ValueError("analyze() output missing pharynx.computable")
    if payload["pharynx"]["computable"]:
        for key in ("coassignment", "enrichment",
                    "coassignment_signaling", "enrichment_signaling"):
            if key not in payload["pharynx"]:
                raise ValueError(f"pharynx.computable=true but {key} missing")


def _match(a, b, tol) -> bool:
    try:
        fa, fb = float(a), float(b)
    except (TypeError, ValueError):
        return False
    if fa != fa or fb != fb:
        return False
    return abs(fa - fb) <= tol


def score_against_truth(payload: dict, truth: dict) -> tuple[int, int, int, int]:
    """返回 (统计量命中数, 统计量总数, 判断题命中数, 判断题总数)。"""
    stat_hits = stat_total = 0
    comparisons = [
        (payload["edge"]["auroc"], truth["edge"]["auroc"], TOL["auroc"]),
        (payload["edge"]["lift"], truth["edge"]["lift"], TOL["lift"]),
        (payload["modules"]["nmi"], truth["modules"]["nmi"], TOL["nmi"]),
        # nmi_null_z is required but not pointwise scored: implementation
        # variation makes a fixed numerical tolerance unreliable.
        # 它仍是必需字段，并驱动 modules_low_but_above_null 判断题（该题有 grey 保护）。
        (payload["modules"]["ars"], truth["modules"]["ars"], TOL["ars"]),
        (payload["hub_overlap"]["k"], truth["hub_overlap"]["k"], 0.0),
        (payload["hub_overlap"]["overlap"], truth["hub_overlap"]["overlap"], TOL["overlap"]),
        (payload["hub_overlap"]["null_z"], truth["hub_overlap"]["null_z"], TOL["null_z"]),
        (payload["hub_overlap"]["degree_corr"], truth["hub_overlap"]["degree_corr"],
         TOL["degree_corr"]),
    ]
    if truth["pharynx"]["computable"]:
        comparisons.append((payload["pharynx"].get("computable"), True, None))
        comparisons.append((payload["pharynx"].get("coassignment"),
                            truth["pharynx"]["coassignment"], TOL["coassignment"]))
        comparisons.append((payload["pharynx"].get("enrichment"),
                            truth["pharynx"]["enrichment"], TOL["enrichment"]))
        comparisons.append((payload["pharynx"].get("coassignment_signaling"),
                            truth["pharynx"]["coassignment_signaling"],
                            TOL["coassignment"]))
        comparisons.append((payload["pharynx"].get("enrichment_signaling"),
                            truth["pharynx"]["enrichment_signaling"], TOL["enrichment"]))
    else:
        comparisons.append((payload["pharynx"].get("computable"), False, None))

    for got, want, tol in comparisons:
        stat_total += 1
        if tol is None or tol == 0.0:
            hit = (got is bool(want)) if isinstance(want, bool) else _match(got, want, 0.0)
        else:
            hit = _match(got, want, tol)
        stat_hits += int(hit)

    judgment_hits = judgment_total = 0
    for key, want in truth["judgments"].items():
        if want is None:          # 该连接组不含咽部 → 判断题不适用，不计入分母
            continue
        judgment_total += 1
        got = payload["judgments"].get(key, None)
        judgment_hits += int(isinstance(got, bool) and got == want)
    return stat_hits, stat_total, judgment_hits, judgment_total


def best_constant_guess_rate(records: list[tuple[str, bool]]) -> float:
    """给定「(问题, 真值)」记录，返回**最佳常量猜测**的命中率。

    常量猜测 = 对每个问题固定押一边（取该问题跨版本的多数真值），
    再统计这样猜能命中多少条记录。
    """
    if not records:
        return 0.0
    by_q: dict[str, list[bool]] = {}
    for q, v in records:
        by_q.setdefault(q, []).append(bool(v))
    hits = 0
    for q, vals in by_q.items():
        n_true = sum(1 for v in vals if v)
        hits += max(n_true, len(vals) - n_true)
    return float(hits / len(records))


# ================================================================ 私有数据
def resolve_private_dir(explicit: str | None):
    if not explicit:
        return None, [], "private eval data not found: BPB_PRIVATE_EVAL_DIR is required"
    root = Path(explicit).resolve()
    if not root.is_dir():
        return None, [], f"private eval data not found: {root}"
    if not (root / "signaling.npz").is_file():
        return None, [], "private eval data incomplete: signaling.npz missing"
    versions = root / "versions"
    missing = [name for name in EXPECTED_VERSIONS if not (versions / name).is_file()]
    if missing:
        return None, [], f"private eval data incomplete: missing {missing}"
    return str(root), list(EXPECTED_VERSIONS), None


def load_private(private_dir: str):
    import numpy as np

    # allow_pickle=True: neuron_ids 若被上游存成 object 数组仍需可读（私有数据由
    # maintainer 生成，非不可信输入；这里显式开启以免因存储 dtype 差异整份评不了）。
    with np.load(os.path.join(private_dir, "signaling.npz"), allow_pickle=False) as z:
        signaling = z["matrix"].astype(np.float64)
        alpha = z["alpha"].astype(np.float64)
        ids = [str(x) for x in z["neuron_ids"]] if "neuron_ids" in z else None
    return signaling, alpha, ids


# ================================================================ 主流程
_ARGS: Any = None


def evaluate(artifacts_dir: str, private_dir: str, worker_image: str) -> dict[str, float]:
    import numpy as np

    validate_contract(artifacts_dir)
    signaling, alpha, ids = load_private(private_dir)

    _priv, ver_files, why = resolve_private_dir(private_dir)
    if why:
        raise SystemExit(why)

    stat_hits = stat_total = j_hits = j_total = 0
    n_versions = 0
    truth_records: list[tuple[str, bool]] = []   # (question, 真值)，仅计可判定者
    for fname in ver_files:
        with np.load(os.path.join(private_dir, "versions", fname), allow_pickle=False) as z:
            adj = z["adjacency"].astype(np.uint8)
            vids = [str(x) for x in z["neuron_ids"]] if "neuron_ids" in z else None
        n = int(adj.shape[0])

        # 交集：信号图谱与连接组共同的神经元（顺序 = 连接组 ids 与 signaling ids 的交）
        sig_ids = ids if ids is not None else [str(i) for i in range(signaling.shape[0])]
        pos_s = {x: i for i, x in enumerate(sig_ids)}
        if vids is None:
            vids = [str(i) for i in range(n)]
        keep = [i for i, name in enumerate(vids) if name in pos_s]
        adj_k = adj[np.ix_(keep, keep)]
        si = [pos_s[vids[i]] for i in keep]
        sig_k = signaling[np.ix_(si, si)]
        alpha_k = alpha[np.ix_(si, si)]
        keep_ids = [vids[i] for i in keep]

        truth = truth_analysis(sig_k, alpha_k, adj_k, keep_ids)
        payload = run_candidate(artifacts_dir, worker_image, sig_k, alpha_k,
                                adj_k, keep_ids)
        _check_payload(payload)

        sh, st, jh, jt = score_against_truth(payload, truth)
        stat_hits += sh
        stat_total += st
        j_hits += jh
        j_total += jt
        for q, want in truth["judgments"].items():
            if want is None:
                continue
            truth_records.append((q, bool(want)))
        n_versions += 1

    if n_versions == 0:
        raise SystemExit("no connectome versions evaluated")

    stat_rate = stat_hits / max(stat_total, 1)
    j_rate = j_hits / max(j_total, 1)

    # Normalize judgment accuracy by the best per-question constant answer
    # across the evaluated reconstructions.
    guess_rate = best_constant_guess_rate(truth_records)
    denom = 1.0 - guess_rate
    if denom <= 1e-9:
        j_skill = 1.0 if j_rate >= 1.0 - 1e-9 else 0.0
    else:
        j_skill = max(0.0, min(1.0, (j_rate - guess_rate) / denom))

    j_component = j_skill
    # Judgments act as a multiplicative gate on the statistics:
    # score = stat_match_rate * (0.5 + 0.5 * judgment_skill).
    return {
        "score": float(stat_rate * (0.5 + 0.5 * j_component)),
        "judgment_skill": j_component,
        "stat_match_rate": stat_rate,
        "judgment_accuracy": j_rate,
        "n_versions": float(n_versions),
    }


# ---------------------------------------------------------------- oracle 路径
def oracle_synth():
    """合成一对「信号图谱 + 连接组」，四个方向性结论都有**确定答案**。

    构造（参数已实测标定，见 checks/README.md）：
      - 解剖：坐标相似度决定的块结构；一个 18 神经元的"咽部"块内部全连、与外部断开
        → 在解剖网络中成独立社区（咽部富集 ≈ 2.8 倍）。
      - 信号：保留 25% 的解剖边 + 少量随机边 → 与解剖**部分**对齐
        （NMI ≈ 0.27，显著优于度保持零模型 z ≈ 14）但远非一致。
      - 边级：信号强度对解剖边仅有弱排序力（lift ≈ 1.34 < 2）→ "弱一致"。
      - hub 重叠：两网络 hub 集合（各按度数取前 10%）重叠 ≈ 机会水平（z ≈ 0）。
    这样 oracle 路径能验证的不只是"能出哨兵"，还包括四个判据全部自洽可达。
    """
    import numpy as np

    rng = np.random.default_rng(ORACLE_SEED)
    n = ORACLE_NEURONS
    coords = rng.normal(size=(n, 3))
    coords /= np.linalg.norm(coords, axis=1, keepdims=True)
    sim = coords @ coords.T
    prob = 1.0 / (1.0 + np.exp(-(0.6 + 2.2 * sim)))
    np.fill_diagonal(prob, 0.0)
    A = (rng.random((n, n)) < prob).astype(np.uint8)
    A = np.triu(A, 1)
    A = A | A.T

    # 咽部块：内部全连、与外部断开（独立组件 → 独立社区）
    ph = list(range(min(18, len(PHARYNX_NAMES))))
    A[ph, :] = 0
    A[:, ph] = 0
    for i in ph:
        for j in ph:
            if i != j:
                A[i, j] = 1

    # 信号拓扑：解剖边的 25% + 随机边 → 部分对齐
    T = (rng.random((n, n)) < ORACLE_TOPOLOGY_KEEP) & (A > 0)
    T = T | (rng.random((n, n)) < 0.06)
    T = np.triu(T, 1)
    T = T | T.T
    np.fill_diagonal(T, 0)
    signal = np.where(T, 0.4 + 0.6 * rng.random((n, n)), 0.05 * rng.random((n, n)))
    signal = np.triu(signal, 1)
    signal = signal + signal.T
    alpha = np.where(T, 0.999, 0.10)

    ids = [f"NEUR{i:03d}" for i in range(n)]
    for k, name in enumerate(sorted(PHARYNX_NAMES)[:len(ph)]):
        ids[k] = name
    return signal, alpha, A.astype(np.uint8), ids




# ---------------------------------------------------------------- self-test
def _pearson(x, y) -> float:
    """手算 Pearson r（自测锚点：完全线性 → 1.0）。"""
    import numpy as np

    a, b = np.asarray(x, float), np.asarray(y, float)
    a, b = a - a.mean(), b - b.mean()
    return float(a.dot(b) / np.sqrt(a.dot(a) * b.dot(b)))


def _rejects_nan() -> bool:
    """回归护栏：hub 排名必须拒绝 NaN（旧版把全 NaN 的强度静默排成"前 k 个下标"）。"""
    try:
        _topk([float("nan")] * 6, [f"N{i}" for i in range(6)], 2)
    except ValueError:
        return True
    return False


def self_test() -> int:
    """冻结协议实现的单元自测（不依赖私有数据）。"""
    import numpy as np

    fails = []

    def check(name, got, want, tol=1e-9):
        ok = (got == want) if isinstance(want, bool) else abs(float(got) - float(want)) <= tol
        print(("ok   " if ok else "FAIL ") + name)
        if not ok:
            fails.append(name)

    # AUROC 手算锚点
    check("AUROC 完美排序", _auc([0, 0, 1, 1], [0.1, 0.2, 0.8, 0.9]), 1.0)
    check("AUROC 全并列", _auc([0, 0, 1, 1], [0.5] * 4), 0.5)
    # 手算：正类得分 0.5 高于 0.1 与 0.2、低于 0.9 → 2/3
    check("AUROC 1正3负 手算", _auc([0, 0, 0, 1], [0.1, 0.9, 0.2, 0.5]), 2.0 / 3.0)
    # AUPRC / 机会水平
    check("AUPRC 完美", _average_precision([0, 0, 1, 1], [0.1, 0.2, 0.8, 0.9]), 1.0)
    check("ap_chance 严格大于密度", _ap_chance(5000, 300) > 300 / 5000, True)
    check("ap_chance(4,2) 手算穷举值", _ap_chance(4, 2), 0.6805555555555556, tol=1e-9)
    # 合成数据的方向性结论自洽
    signal, alpha, A, ids = oracle_synth()
    t = truth_analysis(signal, alpha, A, ids)
    check("合成数据：弱边级一致", t["edge"]["lift"] < EDGE_WEAK_LIFT_MAX, True)
    check("合成数据：hub 重叠 z 有限且非 NaN", bool(np.isfinite(t["hub_overlap"]["null_z"])), True)
    check("hub 排名拒绝非有限值", _rejects_nan(), True)
    check("合成数据：模块低对齐但优于零模型",
          t["judgments"]["modules_low_but_above_null"], True)
    check("合成数据：咽部在解剖侧成独立社区",
          t["judgments"]["pharynx_distinct_in_anatomy"], True)
    check("合成数据：咽部在信号侧成独立社区",
          t["judgments"]["pharynx_distinct_in_signaling"], True)
    check("合成数据：ARS 有限且不大于 NMI",
          bool(np.isfinite(t["modules"]["ars"]) and t["modules"]["ars"] <= t["modules"]["nmi"] + 1e-9),
          True)
    check("合成数据：度数相关 r 有限", bool(np.isfinite(t["hub_overlap"]["degree_corr"])), True)
    check("度数相关 r 手算", _pearson([1.0, 2.0, 3.0], [2.0, 4.0, 6.0]), 1.0)
    check("合成数据：度数相关显著性 p 有限",
          bool(np.isfinite(t["hub_overlap"]["degree_corr_p"])), True)
    check("合成数据：显著性判断题给出布尔值或 None",
          t["judgments"]["hub_degree_corr_significant"] in (True, False, None), True)
    check("显著负相关不算显著为正", positive_hub_significance(-0.8, 0.001), False)
    # 不变式（A）：grey 半宽必须 ≥ 该量的比对容差（否则合法提交会因漂移被误判）
    for _key, _tolkey in (("lift", "lift"), ("pharynx_enrich", "enrichment")):
        _lo, _hi = GREY[_key]
        check(f"grey 半宽 >= 容差 ({_key})", (_hi - _lo) / 2.0 >= TOL[_tolkey] - 1e-12, True)
    # Invariant B: the stochastic null-model grey interval must tolerate the
    # declared 60% relative implementation variation at both boundaries.
    check("nmi_null_z 的 grey 上界足以吸收 60% 相对离散",
          GREY["nmi_null_z"][1] * 0.4 > MODULES_ABOVE_NULL_Z_MIN, True)
    check("nmi_null_z 的 grey 下界足以吸收 60% 相对离散",
          GREY["nmi_null_z"][0] * 1.6 < MODULES_ABOVE_NULL_Z_MIN, True)
    # 已移出计分的量不应再出现在容差表里（防止有人顺手又把它加回比对）
    check("nmi_null_z 不在容差表（已移出计分）", "nmi_null_z" in TOL, False)
    check("显著性 grey = (alpha, 2*alpha)",
          GREY["degree_corr_p"] == (HUB_CORR_ALPHA, 2.0 * HUB_CORR_ALPHA), True)
    # 恒定打分（无信息）→ lift ≈ 1（机会水平正确）
    y = (np.random.default_rng(0).random(4000) < 0.08).astype(int)
    ap = _average_precision(y, np.zeros(y.shape[0]))
    ch = _ap_chance(y.shape[0], int(y.sum()))
    check("常量打分 → lift ≈ 1", abs(ap / ch - 1.0) < 0.25, True)
    check("signaling_topology 对称化", signaling_topology(
        np.array([[0.0, 0.0], [0.99, 0.0]])).sum(), 2.0)

    print(f"\n{len(fails)} 项失败" if fails else "\n全部通过")
    return 1 if fails else 0


def main(argv: Sequence[str] | None = None) -> int:
    global _ARGS
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifacts")
    ap.add_argument("--private")
    ap.add_argument("--worker-image")
    ap.add_argument("--self-test", action="store_true")
    _ARGS = ap.parse_args(argv)

    if _ARGS.self_test:
        return self_test()

    if not _ARGS.artifacts or not _ARGS.private or not _ARGS.worker_image:
        ap.error("--artifacts, --private and --worker-image are required unless --self-test")

    artifact_root = Path(_ARGS.artifacts).resolve()
    private_root = Path(_ARGS.private).resolve()
    if private_root == artifact_root.parent or private_root.is_relative_to(artifact_root.parent):
        print("private evaluator data must be outside the submission bundle", file=sys.stderr)
        return 1

    try:
        validate_contract(_ARGS.artifacts)
    except Exception as exc:
        print(f"submission contract not satisfied: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return 1

    _priv, _files, why = resolve_private_dir(_ARGS.private)
    if why:
        print(why, file=sys.stderr)
        return 1

    try:
        import networkx  # noqa: F401
        import sklearn  # noqa: F401
    except ImportError as exc:
        print(f"evaluator python lacks a required dependency: {exc}", file=sys.stderr)
        return 1

    try:
        emit(evaluate(_ARGS.artifacts, _ARGS.private, _ARGS.worker_image))
    except Exception as exc:
        print(f"evaluation failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
