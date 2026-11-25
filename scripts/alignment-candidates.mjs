/** Offline alignment metadata only; no task code, downloads or acceptance claims. */
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';

const stagedProtocols = new Map([
  ['alignment-l1-cell-tuning', ['unit_tuning_r', 'correlation', 'cell_tuning_cli.py']],
  ['alignment-l2-unit-transfer', ['search_delta_r', 'correlation', 'unit_transfer_cli.py']],
  ['alignment-l3-circuit-paths', ['path_specific_gain', 'nat', 'circuit_paths_cli.py']],
  ['alignment-l4-network-edges', ['network_edge_r', 'correlation', 'network_edges_cli.py']],
]);

export function readAlignmentCandidates(root) {
  const base = join(root, 'tasks/alignment');
  return readdirSync(base, { withFileTypes: true }).filter(e => e.isDirectory() && !e.name.startsWith('_')).flatMap(e => {
    const directory = `tasks/alignment/${e.name}`;
    const dir = join(root, directory);
    if (existsSync(join(dir, 'task.yaml'))) throw new Error(`${directory}: alignment real-data acceptance is pending; cannot be runnable`);
    // The scale-up registry describes planned instances, not candidate task cards.
    // Keep this exception explicit so other incomplete candidate folders still fail.
    if (e.name === 'brainscore') {
      for (const name of ['sources', 'candidates', 'instances']) {
        const manifest = JSON.parse(readFileSync(join(dir, `${name}.json`), 'utf8'));
        const grouped = name === 'instances' && manifest.schema === 'bpb-bs-instances/2';
        const planned = rows => Array.isArray(rows) && rows.every(row => row?.status === 'planned');
        if ((!grouped && manifest.schema !== `bpb-bs-${name}/1`) ||
            (name === 'instances' && !planned(manifest.instances)) || (grouped && !planned(manifest.subtasks)))
          throw new Error(`${directory}: invalid planning registry; run brainscore_cli.py validate`);
      }
      return [];
    }
    const card = JSON.parse(readFileSync(join(dir, 'candidate.json'), 'utf8'));
    if (card.schema !== 'bpb-alignment-candidate/1' || card.id !== e.name || card.domain !== 'alignment' ||
        card.runnable !== false || card.primary_metric?.direction !== 'maximize' || !card.reason)
      throw new Error(`${directory}: invalid pending alignment candidate`);
    const prepared = stagedProtocols.get(card.id);
    if (prepared) {
      const [metric, unit, cli] = prepared;
      if (card.status !== 'preparation_ready_data_pending' || card.primary_metric.id !== metric ||
          card.primary_metric.unit !== unit || card.preparation_entry !== `tasks/alignment/_shared/${cli}` ||
          !existsSync(join(root, card.preparation_entry)) || !existsSync(join(dir, 'README.md')))
        throw new Error(`${directory}: invalid staged alignment task or missing preparation entry`);
      return [{ card, directory }];
    }
    if (card.status !== 'offline_scaffold_data_pending' || card.validated !== false ||
        card.primary_metric.id !== 'analysis_success' || !/^[0-9a-f]{40}$/.test(card.upstream_source_sha))
      throw new Error(`${directory}: invalid pending alignment candidate`);
    for (const file of ['README.md', 'contract.json', 'protocol.json']) {
      if (!existsSync(join(dir, file))) throw new Error(`${directory}: missing ${file}`);
    }
    const protocol = JSON.parse(readFileSync(join(dir, 'protocol.json'), 'utf8'));
    if (protocol.allow_fallback !== false || !['not-implemented-not-accepted', 'implemented-not-validated'].includes(protocol.status) ||
        protocol.upstream.commit !== card.upstream_source_sha)
      throw new Error(`${directory}: candidate protocol binding/status differs`);
    return [{ card, directory }];
  });
}

export function alignmentCatalogRow({ card, directory }) {
  const entry = { task_id: card.id, domain: 'alignment', directory, entry_kind: 'candidate' };
  if (card.status === 'preparation_ready_data_pending')
    return { ...entry, validation: 'preparation_recipe_checked_data_pending', primary_metric: card.primary_metric,
      preparation_available: true, preparation_entry: card.preparation_entry, reason: card.reason };
  return { ...entry,
    validation: 'offline_scaffold_only_not_data_accepted', primary_metric: card.primary_metric,
    source_task_id: card.source_task_id, reason: card.reason,
    agent_benchmark_results: 'not_available' };
}
