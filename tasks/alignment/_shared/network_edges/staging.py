"""Describe and stage one blind L4 experiment for an assigned researcher."""
from pathlib import Path

from multiscale import roi_reference
from unit_transfer.staging import stage_selection_task
from . import METRIC, PROTOCOL


def stage(packet, destination, actor, reference_check=False):
    model = packet.protocol['model']['id']
    question = (
        f'在 {model} 中为 public/protocol.json 指定的五个左侧语言脑区各选择 8 个原生 MLP 单元，'
        '预测增强句相对抑制句的十条脑区共变边变化。每区可独立选择一层（从 0 起）和一个位置 '
        '（pre1 / pre2，句末词首 token 之前第 1 / 2 个 token）。五组的 (layer, unit) 全局互异。'
        '可用 public/ 自行探索。units.npy 的轴为句子、层、位置、单元；responses.npy 为句子、参与者、脑区。'
        'items.json 给出训练条件和各参与者的扫描编号；controls.npy 为 token 数和平均 surprisal。'
        '在本地计算原始数据，研究对话只返回汇总统计、候选映射和查询回执。'
        '固定读出将单元按公开训练句 z 标准化（总体标准差，零标准差用 1），在组内等权平均。每位参与者按条件、session/run 去均值，'
        '分别计算五区之间的十个 Pearson r，取增强减抑制。主分 network_edge_r 为这十条变化在模型'
        '和脑之间的 Pearson r，再对留出参与者等权平均。'
        '提交 choice.json 与可独立复跑的 strategy.py。choice.json 的字段为 packet_sha256'
        '（public/manifest.json 文件的 SHA-256）、groups（各原始 ROI 名映射到 {layer,position,units}）'
        '及 predicted_edge_r（揭晓前对主分的预测，范围 [-1,1]，保留六位小数）。'
        '运行 python query.py choice.json 最多查询两组不同映射的开发分，返回 dev_edge_r，预测值不影响查询。'
        'python strategy.py public feedback.json 必须在标准输出打印最终选择的 JSON；'
        'feedback.json 是按顺序排列的真实回执数组，零次查询为 []。独立复跑只提供公开数据、回执与脚本。'
    )
    spec = {'id': 'alignment-l4-network-edges-' + model, 'domain': 'alignment',
            'category': 'alignment-network-edges', 'version': '0.1-server-draft', 'created_at': '2026-11-25',
            'summary': f'{model} 的五脑区单元映射与共变边预测',
            'timeout_min': 30, 'budget_tokens': None, 'requires': {'network': False, 'gpu': False},
            'expected_artifacts': [{'workspace': 'choice.json'}, {'workspace': 'strategy.py'}],
            'evaluation': {'profile': PROTOCOL, 'primary_metric': {
                'id': METRIC, 'direction': 'maximize', 'unit': 'correlation'}},
            'scoring': {'scorers': [{'kind': 'exec-script', 'script': 'checks/check.sh',
                                     'timeout_min': 5, 'submission_isolation': 'container'}]}}
    cli = Path(__file__).resolve().parents[1] / 'network_edges_cli.py'
    reference = Path(roi_reference.__file__) if reference_check else None
    return stage_selection_task(packet, destination, actor, spec, question, cli, 'l4-measurement.json', reference)
