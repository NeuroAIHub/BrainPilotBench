#!/usr/bin/env python3
"""Execute a frozen submission, validate blind predictions, compute brain-age metrics.

Standalone Python entry; Docker is the default security boundary. Local execution
requires --trusted-local and is solely for trusted code development, never official scoring.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import uuid
import numpy as np

REQUIRED_METRICS = ('score','test_mae','test_pearson_r','test_r2','pearson_r_defined','n_test')
START='>>>>> BPB_SCORES'; END='<<<<< BPB_SCORES'

def json_write(path: Path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,allow_nan=False),encoding='utf-8')

def checked_file(path: Path):
    if path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError(f'Expected regular non-symlink file: {path.name}')

def sha(path: Path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        while block:=f.read(8*1024*1024): h.update(block)
    return h.hexdigest()

def csv_rows(path: Path, columns):
    checked_file(path)
    if path.stat().st_size>8*1024*1024:raise ValueError('CSV exceeds size limit')
    with path.open(newline='',encoding='utf-8-sig') as f:
        reader=csv.DictReader(f)
        if reader.fieldnames!=list(columns):raise ValueError(f'{path.name}: expected columns {list(columns)}')
        rows=list(reader)
    if not rows:raise ValueError(f'{path.name}: empty CSV')
    seen=set()
    for row in rows:
        if set(row)!=set(columns) or any(v is None for v in row.values()):raise ValueError('Malformed CSV row')
        sid=row['subject_id']
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',sid) or re.search(r'IXI\d+',sid,re.I):raise ValueError('Invalid anonymous ID')
        if sid in seen:raise ValueError('Duplicate subject_id')
        seen.add(sid)
    return rows

def numbers(rows, column, expected):
    data={r['subject_id']:float(r[column]) for r in rows}
    if set(data)!=set(expected):raise ValueError(f'{column}: missing or unexpected subjects')
    array=np.array([data[sid] for sid in expected],dtype=np.float64)
    if not np.isfinite(array).all():raise ValueError(f'{column}: non-finite value')
    return array

def compute_metrics(y, prediction):
    y=np.asarray(y,dtype=np.float64);prediction=np.asarray(prediction,dtype=np.float64)
    if y.ndim!=1 or y.shape!=prediction.shape or len(y)<3:raise ValueError('Require matching vectors of >=3 subjects')
    if not np.isfinite(y).all() or not np.isfinite(prediction).all():raise ValueError('Non-finite ages')
    with np.errstate(over='raise',invalid='raise',divide='raise'):
        residual=prediction-y
        mae=float(np.mean(np.abs(residual)))
        a=y-y.mean();b=prediction-prediction.mean()
        sst=float(a@a)
        if sst==0:raise ValueError('Ground-truth ages must have nonzero variance')
        defined=bool(np.any(prediction!=prediction[0]))
        if defined:
            # Scaling centered arrays avoids unstable products for large finite values.
            aa=a/np.max(np.abs(a));bb=b/np.max(np.abs(b))
            r=float(np.clip((aa@bb)/np.sqrt((aa@aa)*(bb@bb)),-1.,1.))
        else:r=0.
        r2=float(1.-(residual@residual)/sst)
        score=float(1./(1.+mae/10.))
    out=dict(score=score,test_mae=mae,test_pearson_r=r,test_r2=r2,pearson_r_defined=int(defined),n_test=len(y))
    if not all(math.isfinite(v) for v in out.values()):raise ValueError('Non-finite metrics')
    return out

def artifacts_root(path: Path):
    if path.is_symlink():raise ValueError('Submission root is a symlink')
    candidate=path/'artifacts'
    if candidate.is_symlink():raise ValueError('Artifact root is a symlink')
    path=path.resolve()
    root=candidate.resolve() if candidate.is_dir() else path
    # Inspect the complete tree before reading metadata or following any child path.
    for p in root.rglob('*'):
        mode=p.lstat().st_mode
        if p.is_symlink() or not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):raise ValueError('Submission contains link/special file')
    for rel in ('scripts/predict.py','models/model_manifest.json','results/validation_predictions.csv','report.md'):
        checked_file(root/rel)
    if (root/'models/model_manifest.json').stat().st_size>2*1024*1024:raise ValueError('Model manifest exceeds size limit')
    manifest=json.loads((root/'models/model_manifest.json').read_text(encoding='utf-8'))
    if not isinstance(manifest,dict):raise ValueError('model_manifest.json must be an object')
    if not (root/'training').is_dir() or not any(p.is_file() for p in (root/'training').rglob('*')):
        raise ValueError('Missing training code/configuration')
    if not any(p.is_file() and p.name!='model_manifest.json' for p in (root/'models').rglob('*')):
        raise ValueError('Missing frozen model files')
    return root

def dataset_inputs(root: Path):
    rows=csv_rows(root/'subjects.csv',('subject_id','image_path'))
    images=root/'images'
    if images.is_symlink() or not images.is_dir():raise ValueError('Invalid hidden image directory')
    filenames=[]
    for row in rows:
        rel=PurePosixPath(row['image_path'])
        if len(rel.parts)!=2 or rel.parts[0]!='images' or not re.fullmatch(r'[A-Za-z0-9_-]+\.nii\.gz',rel.name):
            raise ValueError('Invalid image path')
        checked_file(images/rel.name);filenames.append(rel.name)
    if len(set(filenames))!=len(filenames):raise ValueError('Duplicate image path')
    if {p.name for p in images.iterdir()}!=set(filenames):raise ValueError('Unlisted files in hidden image directory')
    return rows

def snapshot(root):
    return {p.relative_to(root).as_posix():sha(p) for p in sorted(root.rglob('*')) if p.is_file()}

def stage_submission(root, target, max_model_bytes):
    for folder,limit in [('scripts',16*1024*1024),('models',max_model_bytes)]:
        files=[p for p in (root/folder).rglob('*') if p.is_file()]
        if sum(p.stat().st_size for p in files)>limit:raise ValueError(f'{folder} exceeds size limit')
        shutil.copytree(root/folder,target/folder)

def mount(path,target,readonly=False):
    value=str(path.resolve())
    if any(x in value for x in (',','\r','\n')):raise ValueError('Unsupported mount path')
    return f'type=bind,source={value},target={target}'+(',readonly' if readonly else '')

def container_command(args, staged, images, manifest, output, name):
    user=args.container_user or (f'{os.getuid()}:{os.getgid()}' if hasattr(os,'getuid') and os.getuid()>0 and os.getgid()>0 else '65532:65532')
    if not re.fullmatch(r'[1-9]\d*:[1-9]\d*',user):raise ValueError('Non-root numeric uid:gid required')
    if not args.image:raise ValueError('Docker mode requires --image')
    if args.official and not re.search(r'@sha256:[0-9a-fA-F]{64}$',args.image):raise ValueError('Official scoring requires immutable image digest')
    if not re.fullmatch(r'[1-9]\d*[gGmM]',args.memory):raise ValueError('Invalid memory limit')
    if args.cpus<=0:raise ValueError('Invalid CPU limit')
    cmd=[args.docker_binary,'run','--rm','--init','--name',name,'--network','none','--read-only',
         '--cap-drop','ALL','--security-opt','no-new-privileges','--pids-limit','256',
         '--cpus',str(args.cpus),'--memory',args.memory,'--user',user,'--workdir','/work',
         '--tmpfs','/tmp:rw,nosuid,nodev,size=4g','--env','HOME=/tmp','--env','PYTHONHASHSEED=0',
         '--env','OMP_NUM_THREADS='+str(max(1,int(args.cpus))),
         '--mount',mount(staged/'scripts','/submission/scripts',True),
         '--mount',mount(staged/'models','/submission/models',True),
         '--mount',mount(images,'/input/images',True),
         '--mount',mount(manifest,'/input/subjects.csv',True),
         '--mount',mount(output,'/output')]
    if args.gpus!='none':
        if args.gpus!='all' and not re.fullmatch(r'device=\d+',args.gpus):raise ValueError('GPU selection must be all, none, or device=N')
        cmd+=['--gpus',args.gpus]
    bootstrap="import sys,runpy;sys.path.insert(0,'/submission/scripts');sys.argv=['/submission/scripts/predict.py']+sys.argv[1:];runpy.run_path(sys.argv[0],run_name='__main__')"
    return cmd+['--entrypoint','python3',args.image,'-I','-c',bootstrap,
                '--input-dir','/input/images','--input-manifest','/input/subjects.csv',
                '--model-dir','/submission/models','--output-csv','/output/predictions.csv']

def run_logged(cmd,cwd,env,timeout,log,cleanup=None):
    # Drain stdout continuously, cap persisted logs, never forward child score sentinels.
    child=subprocess.Popen(cmd,cwd=cwd,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                           start_new_session=(os.name!='nt'))
    def drain():
        written=0
        with child.stdout as stream,log.open('wb') as f:
            while chunk:=stream.read(65536):
                allowed=min(len(chunk),max(0,1024*1024-written))
                f.write(chunk[:allowed]);written+=allowed
    thread=threading.Thread(target=drain,daemon=True);thread.start()
    try:
        code=child.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        if cleanup:cleanup()
        if os.name!='nt':
            try:os.killpg(child.pid,signal.SIGKILL)
            except ProcessLookupError:pass
        else:child.kill()
        child.wait();thread.join(timeout=5)
        raise TimeoutError('Submitted inference exceeded timeout')
    thread.join(timeout=5)
    if thread.is_alive():raise RuntimeError('Inference log pipe remained open')
    if code!=0:raise RuntimeError(f'Submitted inference failed with exit {code}; inspect inference.log')

def evaluate(args):
    submission=Path(args.submission_dir).resolve()
    candidate=submission/'artifacts' if (submission/'artifacts').is_dir() else submission
    private=Path(args.evaluator_data).resolve()
    output=Path(args.output_dir).resolve()
    for protected in (candidate,private):
        if output==protected or protected in output.parents:raise ValueError('Output must be outside artifacts and private data')
        if output in protected.parents:raise ValueError('Output cannot contain artifacts or private data')
    output.mkdir(parents=True,exist_ok=True,mode=0o700)
    if os.name!='nt':output.chmod(0o700)
    args._safe_output=output
    # Remove stale success payload before any inference starts.
    for name in ('scores.json','predictions.csv'):(output/name).unlink(missing_ok=True)
    json_write(output/'evaluation.json',{'state':'scoring_failed','error':'Evaluation has not completed'})
    if args.official and args.trusted_local:raise ValueError('Official scoring requires Docker')
    if args.timeout_seconds<=0 or args.max_model_bytes<=0:raise ValueError('Limits must be positive')
    root=artifacts_root(submission)
    if not (private/'subjects.csv').is_file() or not (private/'labels/true_ages.csv').is_file():
        raise ValueError('private data missing: require subjects.csv and labels/true_ages.csv')
    rows=dataset_inputs(private);ids=[r['subject_id'] for r in rows]
    before=snapshot(root)
    with tempfile.TemporaryDirectory(prefix='bpb-brain-age-') as temp:
        temp=Path(temp);staged=temp/'submission';staged.mkdir()
        stage_submission(root,staged,args.max_model_bytes)
        pred=temp/'predictions';pred.mkdir();pred.chmod(0o777)
        manifest=temp/'subjects.csv'
        with manifest.open('w',newline='',encoding='utf-8') as f:
            w=csv.writer(f);w.writerow(['subject_id','image_path'])
            w.writerows((r['subject_id'],PurePosixPath(r['image_path']).name) for r in rows)
        if args.trusted_local:
            # This is explicitly NOT a filesystem/network boundary; own reference/tests only.
            env={k:os.environ[k] for k in ('PATH','SYSTEMROOT','WINDIR') if k in os.environ}
            env.update(HOME=str(temp),TMPDIR=str(temp),PYTHONHASHSEED='0',PYTHONNOUSERSITE='1')
            bootstrap=f"import sys,runpy;sys.path.insert(0,{str(staged/'scripts')!r});sys.argv=[{str(staged/'scripts/predict.py')!r}]+sys.argv[1:];runpy.run_path(sys.argv[0],run_name='__main__')"
            cmd=[args.python_binary,'-I','-c',bootstrap,'--input-dir',str(private/'images'),'--input-manifest',str(manifest),
                 '--model-dir',str(staged/'models'),'--output-csv',str(pred/'predictions.csv')]
            run_logged(cmd,temp,env,args.timeout_seconds,output/'inference.log')
        else:
            name='bpb-brain-age-'+uuid.uuid4().hex[:12]
            for p in staged.rglob('*'):p.chmod(0o555 if p.is_dir() else 0o444)
            manifest.chmod(0o444)
            cmd=container_command(args,staged,private/'images',manifest,pred,name)
            env={k:os.environ[k] for k in ('PATH','HOME','SYSTEMROOT','WINDIR','DOCKER_HOST','DOCKER_CONTEXT','DOCKER_TLS_VERIFY','DOCKER_CERT_PATH') if k in os.environ}
            def cleanup():
                subprocess.run([args.docker_binary,'rm','-f',name],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30)
            run_logged(cmd,temp,env,args.timeout_seconds,output/'inference.log',cleanup)
        if snapshot(root)!=before:raise ValueError('Submission artifacts changed during scoring')
        predictions=csv_rows(pred/'predictions.csv',('subject_id','predicted_age'))
        p=numbers(predictions,'predicted_age',ids)
        # Only the trusted parent loads ages. Labels are never mounted or passed to inference.
        y=numbers(csv_rows(private/'labels/true_ages.csv',('subject_id','age')),'age',ids)
        metrics=compute_metrics(y,p)
        with (output/'predictions.csv').open('w',newline='',encoding='utf-8') as f:
            w=csv.writer(f);w.writerow(['subject_id','predicted_age']);w.writerows(zip(ids,p))
    json_write(output/'scores.json',metrics)
    json_write(output/'evaluation.json',{'state':'scored','n_test':len(ids),'isolation':'trusted-local-debug' if args.trusted_local else 'docker',
                'image':args.image,'gpus':args.gpus,'timeout_seconds':args.timeout_seconds,'submission_sha256':before,
                'hidden_manifest_sha256':sha(private/'subjects.csv'),'hidden_labels_sha256':sha(private/'labels/true_ages.csv'),
                'pearson_r_status':'defined' if metrics['pearson_r_defined'] else 'undefined_constant_prediction'})
    return metrics

def parser():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--submission-dir',required=True,help='Bundle containing artifacts/, or artifact directory itself')
    p.add_argument('--evaluator-data',default=os.environ.get('BPB_BRAIN_AGE_EVALUATOR_DIR'))
    p.add_argument('--output-dir',required=True)
    p.add_argument('--image',default=os.environ.get('BPB_INFERENCE_IMAGE'))
    p.add_argument('--official',action='store_true');p.add_argument('--trusted-local',action='store_true')
    p.add_argument('--python-binary',default=sys.executable);p.add_argument('--docker-binary',default='docker')
    p.add_argument('--gpus',default='all');p.add_argument('--cpus',type=float,default=4)
    p.add_argument('--memory',default='32g');p.add_argument('--container-user')
    p.add_argument('--timeout-seconds',type=int,default=1800)
    p.add_argument('--max-model-bytes',type=int,default=1024**3)
    p.add_argument('--bpb-sentinel',action='store_true')
    return p

def main():
    args=parser().parse_args()
    try:
        if not args.evaluator_data:raise ValueError('private data missing: provide --evaluator-data or BPB_PRIVATE_EVAL_DIR')
        metrics=evaluate(args)
    except Exception as exc:
        if hasattr(args,'_safe_output'):
            (args._safe_output/'scores.json').unlink(missing_ok=True)
            json_write(args._safe_output/'evaluation.json',{'state':'scoring_failed','error':str(exc)})
        print(f'brain-age scoring failed: {exc}',file=sys.stderr)
        return 1  # No numeric success payload or BPB sentinel on failure.
    if args.bpb_sentinel:print(START)
    print(json.dumps(metrics,allow_nan=False,sort_keys=True))
    if args.bpb_sentinel:print(END)
    return 0

if __name__=='__main__':raise SystemExit(main())
