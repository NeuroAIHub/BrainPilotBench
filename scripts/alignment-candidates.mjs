/** Offline alignment metadata only; no task code, downloads or acceptance claims. */
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';

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
        if (manifest.schema !== `bpb-bs-${name}/1` || (name === 'instances' &&
            (!Array.isArray(manifest.instances) || manifest.instances.some(i => i.status !== 'planned'))))
          throw new Error(`${directory}: invalid planning registry; run brainscore_cli.py validate`);
      }
      return [];
    }
    const card = JSON.parse(readFileSync(join(dir, 'candidate.json'), 'utf8'));
    if (card.schema !== 'bpb-alignment-candidate/1' || card.id !== e.name || card.domain !== 'alignment' ||
        card.status !== 'offline_scaffold_data_pending' || card.runnable !== false || card.validated !== false ||
        card.primary_metric?.id !== 'analysis_success' || card.primary_metric?.direction !== 'maximize' ||
        !/^[0-9a-f]{40}$/.test(card.upstream_source_sha) || !card.reason)
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
  return { task_id: card.id, domain: 'alignment', directory, entry_kind: 'candidate',
    validation: 'offline_scaffold_only_not_data_accepted', primary_metric: card.primary_metric,
    source_task_id: card.source_task_id, reason: card.reason,
    agent_benchmark_results: 'not_available' };
}
