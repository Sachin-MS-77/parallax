"""Explicit analyst-labelled ensemble update, versioned and never automatic."""
import json
from pathlib import Path

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss
from sklearn.model_selection import train_test_split

from .model import load_model
from .storage import connect, file_hash, digest

COMPONENTS=['taint','behavioral_link','timing','address_reuse','network_exposure']


def feedback_update(db_path, model_dir, labels_path, out):
    labels=json.loads(Path(labels_path).read_text())
    bundle,manifest=load_model(model_dir)
    db=connect(db_path)
    rows=[json.loads(r[0]) for r in db.execute('SELECT payload FROM alerts ORDER BY address')]
    sources=[r[0] for r in db.execute('SELECT hash FROM sources')]; db.close()
    rows=[r for r in rows if r['address'] in labels]
    if len(rows)<20: raise ValueError('Feedback requires at least 20 explicitly labelled scored profiles')
    y=np.asarray([labels[r['address']] for r in rows])
    if set(y)!={0,1} or min(np.bincount(y.astype(int)))<5:
        raise ValueError('Feedback requires 0/1 labels with at least 5 examples of each class')
    x=np.asarray([[r['subscores'][k]['value'] if r['subscores'][k]['value'] is not None else 0 for k in COMPONENTS] +
                  [int(r['subscores'][k]['value'] is not None) for k in COMPONENTS] for r in rows])
    train_idx,hold_idx=train_test_split(np.arange(len(y)),test_size=.3,stratify=y,random_state=41)
    model=LogisticRegression(C=1,max_iter=1000).fit(x[train_idx],y[train_idx])
    out=Path(out)
    if out.exists(): raise ValueError('Choose a new model version directory')
    out.mkdir(parents=True)
    bundle['feedback']={'model':model,'components':COMPONENTS}
    report={'label_sha256':file_hash(labels_path),'sources':sources,
            'address_hashes':[digest(r['address']) for r in rows],
            'end_time':max(r['last_seen'] for r in rows),
            'training_profiles':len(train_idx),'holdout_profiles':len(hold_idx),
            'holdout_brier':float(brier_score_loss(y[hold_idx],model.predict_proba(x[hold_idx])[:,1])),
            'scope':'Selected analyst-labelled sample only; selection bias and entity dependence remain',
            'coefficients':model.coef_[0].tolist()}
    joblib.dump(bundle,out/'model.joblib')
    manifest.update({'feedback':report,'artifact_sha256':file_hash(out/'model.joblib'),
                     'parent_model_sha256':manifest['artifact_sha256'],
                     'priority_formula':'Configured five-term Fracture Index; feedback logistic estimate reported separately'})
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2))
    return report
