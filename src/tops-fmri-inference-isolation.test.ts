import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";

const EVALUATOR = join(process.cwd(), "tasks", "tops-fmri", "checks", "evaluate_external.py");

test("tops-fMRI Docker inference cannot read labels, host credentials, or the network", {
  skip: process.env.BPB_DOCKER_TEST !== "1" || !process.env.BPB_TEST_INFERENCE_IMAGE
    ? "set BPB_DOCKER_TEST=1 and BPB_TEST_INFERENCE_IMAGE after building docker/inference/Dockerfile"
    : false,
}, () => {
  const root = mkdtempSync(join(tmpdir(), "bpb-private-inference-"));
  const runDir = join(root, "run");
  const privateDir = join(root, "evaluator-private");
  const scriptsDir = join(runDir, "artifacts", "scripts");
  const modelsDir = join(runDir, "artifacts", "models");
  const featuresDir = join(privateDir, "features");
  const labelsDir = join(privateDir, "labels");
  const hostSecret = join(labelsDir, "host-secret.txt");
  try {
    for (const dir of [scriptsDir, modelsDir, featuresDir, labelsDir]) mkdirSync(dir, { recursive: true });
    writeFileSync(join(modelsDir, "model.txt"), "public-model");
    writeFileSync(hostSecret, "private-label-secret");
    const seed = spawnSync("python3", ["-c", [
      "import numpy as np, pathlib",
      `f=pathlib.Path(${JSON.stringify(featuresDir)}); l=pathlib.Path(${JSON.stringify(labelsDir)})`,
      "x=np.arange(6,dtype=float).reshape(3,2)",
      "np.savez(f/'study4_features.npz', SBP_SP=x, SBP_REST=x, CBP_SP=x, CBP_REST=x)",
      "np.savez(f/'study5_features.npz', JP=x, UK=x)",
      "np.savez(l/'study4_labels.npz', SBP_SP=[0.,1.,2.], SBP_REST=[0.,1.,2.], CBP_SP=[0.,1.,2.], CBP_REST=[0.,1.,2.])",
      "np.savez(l/'study5_labels.npz', JP=[0,0,1], UK=[0,1,1])",
    ].join("; ")], { encoding: "utf8" });
    assert.equal(seed.status, 0, seed.stderr);

    writeFileSync(join(scriptsDir, "apply_signature.py"), `
import argparse, csv, os, pathlib, socket
import numpy as np
p=argparse.ArgumentParser()
p.add_argument('--eval-features-dir', required=True)
p.add_argument('--model-dir', required=True)
p.add_argument('--out-dir', required=True)
a=p.parse_args()
forbidden=[k for k in os.environ if 'TOKEN' in k or 'PRIVATE' in k or 'EVAL' in k]
if forbidden or pathlib.Path(${JSON.stringify(hostSecret)}).exists():
    raise SystemExit('host secret or environment leaked')
try:
    socket.create_connection(('1.1.1.1', 53), timeout=0.5)
except OSError:
    pass
else:
    raise SystemExit('network leaked')
for protected in [pathlib.Path(a.model_dir)/'mutation', pathlib.Path(a.eval_features_dir)/'mutation']:
    try:
        protected.write_text('bad')
    except OSError:
        pass
    else:
        raise SystemExit('read-only input was writable')
out=pathlib.Path(a.out_dir); out.mkdir(parents=True, exist_ok=True)
s4=np.load(pathlib.Path(a.eval_features_dir)/'study4_features.npz')
with (out/'study4_predictions.csv').open('w', newline='') as f:
    w=csv.writer(f); w.writerow(['condition','sample_id','signature_response'])
    for group in ['SBP_SP','SBP_REST','CBP_SP','CBP_REST']:
        for i in range(s4[group].shape[0]): w.writerow([group,i,float(i)])
s5=np.load(pathlib.Path(a.eval_features_dir)/'study5_features.npz')
with (out/'study5_predictions.csv').open('w', newline='') as f:
    w=csv.writer(f); w.writerow(['site','sample_id','signature_response'])
    for group in ['JP','UK']:
        for i in range(s5[group].shape[0]): w.writerow([group,i,float(i)])
`);

    const result = spawnSync("python3", [EVALUATOR, runDir], {
      encoding: "utf8",
      timeout: 180_000,
      env: {
        ...process.env,
        HF_TOKEN: "must-not-reach-submission",
        BPB_TOPS_PRIVATE_EVAL_DIR: privateDir,
        BPB_SUBMISSION_ISOLATION: "docker",
        BPB_INFERENCE_IMAGE: process.env.BPB_TEST_INFERENCE_IMAGE!,
      },
    });
    assert.equal(result.status, 0, `${result.stderr}\n${result.stdout}`);
    assert.match(result.stdout, />>>>> BPB_SCORES/);
    assert.match(result.stdout, /"score":/);
    assert.doesNotMatch(result.stderr, /leaked|writable/i);
  } finally {
    rmSync(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 });
  }
});
