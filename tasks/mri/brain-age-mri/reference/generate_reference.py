#!/usr/bin/env python3
"""Fit and freeze a low-cost MRI/Ridge reference using public subjects only."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import numpy as np
from sklearn.linear_model import Ridge
from sklearn.model_selection import KFold
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

# This exact preprocessing/inference source is embedded in the frozen reference bundle.
# All image-dependent operations are per-image; learned scaler/model are train-only.
PREDICT_SOURCE = r'''#!/usr/bin/env python3
import argparse,csv,json
from pathlib import Path,PurePosixPath
import nibabel as nib
import numpy as np
from scipy.ndimage import zoom

def read_inputs(path):
    with Path(path).open(newline='',encoding='utf-8-sig') as f:
        reader=csv.DictReader(f)
        if reader.fieldnames!=['subject_id','image_path']:raise ValueError('Invalid input manifest columns')
        rows=list(reader)
    ids=[r['subject_id'] for r in rows]
    if not rows or len(set(ids))!=len(ids):raise ValueError('Empty/duplicate subjects')
    return rows

def extract_features(image_dir,rows,shape):
    root=Path(image_dir).resolve();features=[]
    for i,row in enumerate(rows,1):
        rel=PurePosixPath(row['image_path'])
        parts=rel.parts[1:] if rel.parts and rel.parts[0]=='images' else rel.parts
        if not parts or '..' in parts or rel.is_absolute():raise ValueError('Invalid image path')
        path=root.joinpath(*parts).resolve()
        if root not in path.parents:raise ValueError('Image outside input directory')
        image=nib.as_closest_canonical(nib.load(path))
        values=image.get_fdata(dtype=np.float32)
        if values.ndim!=3 or not np.isfinite(values).all():raise ValueError('Invalid MRI data')
        positive=values[values>0]
        if positive.size<16:raise ValueError('Insufficient positive MRI voxels')
        low,high=np.percentile(positive,[1,99])
        if high<=low:raise ValueError('Constant MRI intensities')
        values=np.clip((values-low)/(high-low),0,1)
        small=zoom(values,np.array(shape)/np.array(values.shape),order=1,prefilter=False,mode='nearest',grid_mode=False)
        if small.shape!=tuple(shape):raise ValueError('Unexpected resampling shape')
        features.append(small.reshape(-1).astype(np.float32))
        if i%50==0:print(f'Features {i}/{len(rows)}',flush=True)
    return np.stack(features)

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--input-dir',required=True);p.add_argument('--input-manifest',required=True)
    p.add_argument('--model-dir',required=True);p.add_argument('--output-csv',required=True)
    a=p.parse_args();rows=read_inputs(a.input_manifest)
    manifest=json.loads((Path(a.model_dir)/'model_manifest.json').read_text())
    shape=tuple(manifest['feature_shape'])
    if len(shape)!=3 or min(shape)<2:raise ValueError('Invalid feature grid')
    with np.load(Path(a.model_dir)/'brain_age_ridge.npz',allow_pickle=False) as z:
        coefficient=z['coefficient'];intercept=float(z['intercept'])
    x=extract_features(a.input_dir,rows,shape)
    if coefficient.shape!=(x.shape[1],):raise ValueError('Wrong model feature dimension')
    prediction=x.astype(np.float64)@coefficient+intercept
    if not np.isfinite(prediction).all():raise ValueError('Non-finite predictions')
    output=Path(a.output_csv);output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('w',newline='',encoding='utf-8') as f:
        w=csv.writer(f);w.writerow(['subject_id','predicted_age'])
        w.writerows((r['subject_id'],float(v)) for r,v in zip(rows,prediction))
if __name__=='__main__':main()
'''

def json_write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,allow_nan=False),encoding='utf-8')

def table(path,columns):
    with path.open(newline='',encoding='utf-8-sig') as f:
        reader=csv.DictReader(f)
        if reader.fieldnames!=list(columns):raise ValueError(f'Invalid columns: {path.name}')
        rows=list(reader)
    if not rows or len({r['subject_id'] for r in rows})!=len(rows):raise ValueError('Empty/duplicate subjects')
    return rows

def ages(path,ids):
    data={r['subject_id']:float(r['age']) for r in table(path,('subject_id','age'))}
    if set(data)!=set(ids):raise ValueError('Age/subject mismatch')
    values=np.array([data[sid] for sid in ids])
    if not np.isfinite(values).all() or np.any(values<=0):raise ValueError('Invalid chronological ages')
    return values

def write_predictions(path,ids,values,true=None):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',newline='',encoding='utf-8') as f:
        w=csv.writer(f)
        if true is None:
            w.writerow(['subject_id','predicted_age']);w.writerows(zip(ids,map(float,values)))
        else:
            w.writerow(['subject_id','true_age','predicted_age']);w.writerows(zip(ids,map(float,true),map(float,values)))

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        while block:=f.read(8*1024*1024):h.update(block)
    return h.hexdigest()

def generate(args):
    public=Path(args.agent_data).resolve();out=Path(args.output_dir).resolve()
    for source in (public,):
        if out==source or source in out.parents or out in source.parents:raise ValueError('Reference output must be separate from both input data roots')
    if out.exists():raise ValueError('Reference output already exists; choose a new directory')
    if args.folds<2 or args.threads<1:raise ValueError('Invalid folds/threads')
    shape=tuple(args.feature_shape)
    if len(shape)!=3 or min(shape)<2:raise ValueError('Invalid feature shape')
    if any(not np.isfinite(a) or a<=0 for a in args.alphas):raise ValueError('Alphas must be positive')
    out.mkdir(parents=True)
    # This embedded, reviewed source is part of the task, not submitted code.
    ns={'__name__':'reference_feature_module'};exec(compile(PREDICT_SOURCE,'reference_predict.py','exec'),ns)
    inputs=ns['read_inputs'](public/'subjects.csv');ids=[r['subject_id'] for r in inputs]
    y=ages(public/'ages.csv',ids)
    if args.folds>len(ids):raise ValueError('Not enough public subjects for CV')
    x=ns['extract_features'](public/'images',inputs,shape)
    cv=KFold(args.folds,shuffle=True,random_state=args.seed)
    folds=list(cv.split(x));cv_rows=[];predictions={}
    with threadpool_limits(limits=args.threads):
        for alpha in sorted(set(args.alphas)):
            oof=np.empty(len(y),dtype=np.float64)
            for train,valid in folds:
                scaler=StandardScaler();xt=scaler.fit_transform(x[train].astype(np.float64))
                model=Ridge(alpha=alpha,solver='cholesky')
                model.fit(xt,y[train]);oof[valid]=model.predict(scaler.transform(x[valid].astype(np.float64)))
            cv_rows.append({'alpha':alpha,'public_oof_mae':float(np.mean(np.abs(oof-y)))})
            predictions[alpha]=oof
            print(json.dumps(cv_rows[-1]),flush=True)
        best=min(cv_rows,key=lambda r:(r['public_oof_mae'],r['alpha']))['alpha']
        scaler=StandardScaler();xt=scaler.fit_transform(x.astype(np.float64))
        model=Ridge(alpha=best,solver='cholesky');model.fit(xt,y)
        raw_coefficient=model.coef_/scaler.scale_
        raw_intercept=float(model.intercept_-scaler.mean_@raw_coefficient)
        np.testing.assert_allclose(x.astype(np.float64)@raw_coefficient+raw_intercept,model.predict(xt),rtol=1e-8,atol=1e-8)
    artifacts=out/'reference_submission'/'artifacts'
    for folder in ('scripts','models','training','results'):(artifacts/folder).mkdir(parents=True)
    (artifacts/'scripts/predict.py').write_text(PREDICT_SOURCE,encoding='utf-8')
    np.savez(artifacts/'models/brain_age_ridge.npz',coefficient=raw_coefficient,intercept=np.float64(raw_intercept))
    json_write(artifacts/'models/model_manifest.json',{'model_type':'voxel_ridge','model_files':['brain_age_ridge.npz'],
        'feature_shape':list(shape),'preprocessing':'Per-image RAS+ axis orientation; positive-voxel 1st/99th percentile intensity scaling, clip 0..1; linear interpolation over entire image field of view. No skull stripping or anatomical registration.',
        'selected_alpha':best,'public_cv_folds':args.folds,'seed':args.seed,'training_subjects':len(ids),
        'runtime_dependencies':['numpy','scipy','nibabel'],'model_selection':'public subject-level CV only; hidden outcomes never used for selection'})
    write_predictions(artifacts/'results/validation_predictions.csv',ids,predictions[best],y)
    shutil.copy2(Path(__file__),artifacts/'training/generate_reference.py')
    json_write(artifacts/'training/config.json',{'seed':args.seed,'folds':args.folds,'alphas':args.alphas,'feature_shape':list(shape)})
    (artifacts/'report.md').write_text('# CPU MRI/Ridge reference baseline\n\nFixed preprocessing and public-only subject CV, followed by refit on the complete public pool.\n\nThe chosen CV result was used for hyperparameter selection and is not an independent final test estimate. No hidden outcomes are used to select alpha or preprocess the model. This coarse voxel baseline does not provide anatomical registration or a state-of-the-art brain-age model.\n',encoding='utf-8')
    json_write(out/'reference_submission/meta.json',{'taskId':'brain-age-mri','agent':'maintainer-cpu-ridge-reference','taskVersion':'0.1-candidate'})
    result={'public_cv':cv_rows,'selected_alpha':best,'public_subjects':len(ids),
            'public_age_median':float(np.median(y)),'hidden_data_accessed':False}
    json_write(out/'public_reference_summary.json',result)
    json_write(out/'provenance.json',{'seed':args.seed,'feature_shape':list(shape),
        'source_sha256':{str(p.relative_to(public)):digest(p) for p in (public/'subjects.csv',public/'ages.csv')},
        'script_sha256':digest(Path(__file__)),'model_sha256':digest(artifacts/'models/brain_age_ridge.npz'),
        'python':sys.version,'numpy':np.__version__})
    json_write(out/'COMPLETE.json',{'status':'public_reference_frozen','n_public':len(y)})
    if os.name!='nt':
        out.chmod(0o700)
        for p in out.rglob('*'):p.chmod(0o700 if p.is_dir() else 0o600)
    print(json.dumps(result,indent=2),flush=True)
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--agent-data',required=True);p.add_argument('--output-dir',required=True)
    p.add_argument('--seed',type=int,default=42);p.add_argument('--folds',type=int,default=2)
    p.add_argument('--feature-shape',nargs=3,type=int,default=[12,12,12])
    p.add_argument('--alphas',nargs='+',type=float,default=[100])
    p.add_argument('--threads',type=int,default=2)
    args=p.parse_args()
    try:generate(args)
    except Exception as e:
        print(f'Reference generation failed: {e}; an output without COMPLETE.json is unfinished.',file=sys.stderr)
        return 1
    return 0
if __name__=='__main__':raise SystemExit(main())
