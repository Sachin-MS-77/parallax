"""Persisted Isolation Forests with explicit ranking and synthetic calibration."""
import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import sklearn
from sklearn.cluster import KMeans
from sklearn.ensemble import IsolationForest
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from . import __version__
from .features import CHAIN_FEATURES, FEATURES, build_features, matrix
from .storage import audit, canonical, connect, digest, file_hash, get_meta, set_meta


def rank_score(model, x, reference):
    raw = -model.score_samples(x)
    # Empirical reference percentile; neither a calibrated probability nor a p-value.
    reference = np.asarray(reference)
    return np.searchsorted(reference, raw, side="right") / len(reference), raw


def train(db_path, model_dir, calibration_db=None, labels_path=None, seed=41, graph_labels=None):
    db = connect(db_path)
    rows = build_features(db)
    source_hashes = [r[0] for r in db.execute("SELECT hash FROM sources ORDER BY hash")]
    db.close()
    if len(rows) < 20:
        raise ValueError("Training requires at least 20 input-address profiles")
    model_dir = Path(model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)
    if (model_dir / "model.joblib").exists():
        raise ValueError("Model directory already contains a model; choose a new version directory")
    x = matrix(rows)
    models, references = {}, {}
    for name, names in (("chain", CHAIN_FEATURES), ("fused", FEATURES)):
        model = IsolationForest(n_estimators=160, max_samples=min(256, len(rows)), random_state=seed, n_jobs=1)
        model.fit(matrix(rows, names))
        models[name] = model
        references[name] = np.sort(-model.score_samples(matrix(rows, names)))
    scaler = StandardScaler().fit(x)
    clusters = KMeans(n_clusters=min(8, len(rows)), n_init=10, random_state=seed).fit(scaler.transform(x))
    bundle = {"models": models, "references": references, "median": np.median(x, axis=0),
              "scale": np.maximum(np.std(x, axis=0), 1e-6), "scaler": scaler, "clusters": clusters,
              "calibrator": None, "graph": None}
    if graph_labels:
        from .graphml import fit_graph
        gt = json.loads(Path(graph_labels).read_text())
        if gt.get('split') != 'train': raise ValueError('Graph labels must belong to training split')
        bundle['graph'] = fit_graph(rows,gt['labels'],seed)
    calibration = None
    if calibration_db or labels_path:
        if not calibration_db or not labels_path:
            raise ValueError("Both calibration DB and labels are required")
        cdb = connect(calibration_db)
        cal_rows = build_features(cdb)
        cal_hashes = [r[0] for r in cdb.execute("SELECT hash FROM sources")]
        cdb.close()
        if set(source_hashes) & set(cal_hashes) or {r["address"] for r in rows} & {r["address"] for r in cal_rows}:
            raise ValueError("Training and calibration data must be source- and address-disjoint")
        if max(r["last_seen"] for r in rows) >= min(r["first_seen"] for r in cal_rows):
            raise ValueError("Calibration must follow the training time window")
        truth = json.loads(Path(labels_path).read_text())
        if truth.get("domain") != "synthetic" or truth.get("split") != "calibration":
            raise ValueError("This prototype's optional calibrator requires synthetic calibration labels")
        y = np.asarray([truth["labels"][r["address"]]["label"] for r in cal_rows])
        if len(np.unique(y)) != 2:
            raise ValueError("Calibration needs both benign and positive examples")
        _, raw = rank_score(models["fused"], matrix(cal_rows), references["fused"])
        inputs = np.column_stack((raw, [r["rule_score"] for r in cal_rows]))
        calibrator = LogisticRegression(C=10, random_state=seed).fit(inputs, y)
        bundle["calibrator"] = calibrator
        calibration = {"scope": "synthetic generator only; not validated on real investigations", "rows": len(y),
                       "positive_rate": float(y.mean()), "source_hashes": cal_hashes, "labels_sha256": file_hash(labels_path),
                       "address_hashes": [digest(r["address"]) for r in cal_rows], "end_time": max(r["last_seen"] for r in cal_rows)}
    artifact = model_dir / "model.joblib"
    joblib.dump(bundle, artifact)
    manifest = {"version": __version__, "feature_schema": "address-v2", "features": FEATURES,
                "algorithm": "IsolationForest", "trees": 160, "training_profiles": len(rows),
                "seed": seed, "sklearn_version": sklearn.__version__, "training_sources": source_hashes,
                "training_address_hashes": [digest(r["address"]) for r in rows],
                "training_end_time": max(r["last_seen"] for r in rows),
                "calibration": calibration, "created_at": datetime.now(timezone.utc).isoformat(),
                "artifact_sha256": file_hash(artifact),
                "graph_model": {k:v for k,v in bundle['graph'].items() if k not in ('state','mean','scale')} if bundle['graph'] else None,
                "graph_labels_sha256":file_hash(graph_labels) if graph_labels else None,
                "priority_formula": "Normalized available weights: anomaly .40, graph .15, seed proximity .15, behavioral .10, timing .08, reuse .07, relay association .05",
                "explanation": "Tree SHAP explains Isolation Forest mean path length; negative contributions increase anomalousness. Separate rule and graph evidence."}
    # Fit the decision threshold on calibration only, before touching held-out data.
    manifest['priority_threshold'] = 80.0
    manifest['threshold_policy'] = 'Default heuristic threshold; no labelled calibration supplied'
    if calibration:
        from sklearn.metrics import f1_score
        ca = predict(cal_rows,bundle,manifest,explanations=False)
        cy = np.asarray([truth['labels'][a['address']]['label'] for a in ca])
        cp = np.asarray([a['priority'] for a in ca])
        candidates = sorted(set(cp))
        threshold=max(candidates,key=lambda t:(f1_score(cy,cp>=t,zero_division=0),t))
        manifest['priority_threshold']=float(threshold)
        manifest['threshold_policy']='Threshold maximizes F1 on separate calibration profiles; frozen before test evaluation'
    manifest.update({'priority_threshold':60.000001,'review_threshold':30.000001,
                     'threshold_policy':'Fixed Fracture Index bands: Low <=30, Moderate <=60, High >60',
                     'priority_formula':'Five-term configured Fracture Index; missing evidence contributes zero'})
    (model_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def load_model(model_dir):
    model_dir = Path(model_dir)
    manifest = json.loads((model_dir / "manifest.json").read_text())
    if manifest["features"] != FEATURES or manifest["sklearn_version"] != sklearn.__version__:
        raise ValueError("Model feature schema or sklearn version mismatch; retrain locally")
    if file_hash(model_dir / "model.joblib") != manifest["artifact_sha256"]:
        raise ValueError("Model hash mismatch")
    # Joblib is intentionally only read from the operator-selected local model directory.
    return joblib.load(model_dir / "model.joblib"), manifest


def predict(rows, bundle, manifest, domain="unknown", explanations=True):
    if not rows:
        return []
    x = matrix(rows)
    fused, raw = rank_score(bundle["models"]["fused"], x, bundle["references"]["fused"])
    chain, _ = rank_score(bundle["models"]["chain"], matrix(rows, CHAIN_FEATURES), bundle["references"]["chain"])
    clusters = bundle["clusters"].predict(bundle["scaler"].transform(x))
    from .graphml import infer_graph
    graph_scores, embeddings = infer_graph(rows,bundle.get('graph'))
    probability = [None] * len(rows)
    if domain == "synthetic" and bundle["calibrator"] is not None:
        probability = bundle["calibrator"].predict_proba(np.column_stack((raw, [r["rule_score"] for r in rows])))[:, 1]
    changes = None
    shap_values, shap_base = None, None
    if explanations:
        import shap
        explainer = shap.TreeExplainer(bundle['models']['fused'])
        shap_values = np.asarray(explainer.shap_values(x))
        shap_base = float(np.asarray(explainer.expected_value).ravel()[0])
        changed = np.repeat(x, len(FEATURES), axis=0)
        for i in range(len(rows)):
            for j in range(len(FEATURES)):
                changed[i * len(FEATURES) + j, j] = bundle["median"][j]
        replaced_raw = -bundle["models"]["fused"].score_samples(changed)
        changes = raw[:, None] - replaced_raw.reshape(len(rows), len(FEATURES))
    result = []
    for i, row in enumerate(rows):
        f=row['features']
        components={'anomaly':(float(fused[i]),.40),
                    'graph':(float(graph_scores[i]) if graph_scores is not None else None,.15),
                    'seed_proximity':((1/(1+row['seed_distance']) if row['seed_distance'] is not None else 0) if f['seed_evidence_available'] else None,.15),
                    'behavioral':(row['rule_score'],.10),
                    'timing':(float(np.clip(1-f['log_median_gap_seconds']/np.log1p(3600),0,1)),.08),
                    'address_reuse':(float(any(r['name']=='Address reuse' for r in row['rules'])),.07),
                    'relay_association':(min(1,len(row.get('network_associations',[]))/3) if row['network_coverage'] else None,.05)}
        # Preserve detector scores separately; the Fracture Index uses the stated five-term formula.
        detector_components = components
        weights = row['fracture_config']['weights']
        values = {
            'taint': row['taint']['fraction'] if row['taint']['available'] else None,
            'behavioral_link': max(float(fused[i]), float(graph_scores[i]) if graph_scores is not None else 0,
                                   row['rule_score'], row['behavioral_drift']['score']),
            'timing': max(components['timing'][0], row['behavioral_drift']['score']),
            'address_reuse': float(any(r['name'] in ('Address reuse','Address reuse after mixing pattern') for r in row['rules'])),
            'network_exposure': min(1.,len(row.get('network_associations',[]))/3) if row['network_coverage'] else None}
        components = {k:(v,weights[k]) for k,v in values.items()}
        score = round(100*sum((v or 0)*weights[k] for k,v in values.items()),2)
        feedback_probability = None
        if bundle.get('feedback'):
            keys=bundle['feedback']['components']
            fx=[[(values[k] or 0) for k in keys]+[int(values[k] is not None) for k in keys]]
            feedback_probability=float(bundle['feedback']['model'].predict_proba(fx)[0,1])
        band = 'High' if score>60 else 'Moderate' if score>30 else 'Low'
        available = 1
        reasons = []
        if explanations:
            for j in np.argsort(shap_values[i])[:6]:
                reasons.append({"feature": FEATURES[j], "value": round(float(x[i, j]), 6),
                                "training_median": round(float(bundle["median"][j]), 6),
                                "anomaly_score_delta": round(float(changes[i, j]), 6),
                                "shap_path_length":round(float(shap_values[i,j]),6)})
        result.append({**{k: v for k, v in row.items() if k != "vector"},
                       "priority": score, "priority_band": "High" if score>60 else "Review" if score>30 else "Low",
                       "confidence_band":band,
                       "confidence_scope":"Score band only; not calibrated certainty",
                       "feedback_model_probability":feedback_probability,
                       "component_coverage":sum(weights[k] for k,v in values.items() if v is not None),
                       "detector_scores":{k:{'value':v,'weight':w} for k,(v,w) in detector_components.items()},
                       "model_percentile": round(float(fused[i]) * 100, 2),
                       "chain_percentile": round(float(chain[i]) * 100, 2),
                       "raw_anomaly_score": round(float(raw[i]), 6),
                       "synthetic_probability": round(float(probability[i]), 4) if probability[i] is not None else None,
                       "probability_scope": "Synthetic benchmark only" if probability[i] is not None else "Uncalibrated for this data",
                       "subscores":{k:{'value':v,'weight':w} for k,(v,w) in components.items()},
                       "graph_score":float(graph_scores[i]) if graph_scores is not None else None,
                       "shap_base_path_length":shap_base,
                       "shap_values":shap_values[i].tolist() if explanations else None,
                       "reason":'; '.join(r['name'] for r in row['rules']) or 'Unusual combined transaction/network profile relative to training data',
                       "behavior_group": int(clusters[i]) + 1, "model_sha256": manifest["artifact_sha256"],
                       "explanations": reasons, "status": "New"})
    from .analysis import case_note
    for alert in result:
        alert['case_note'] = case_note(alert)
    return sorted(result, key=lambda r: (-r["priority"], r["address"]))


def score(db_path, model_dir):
    bundle, manifest = load_model(model_dir)
    manifest = {**manifest, 'priority_threshold':60.000001,'review_threshold':30.000001,
                'priority_formula':'Fracture Index: configured five-term weighted sum; unknown components contribute zero'}
    db = connect(db_path)
    rows = build_features(db)
    domain = get_meta(db, "domain", "unknown")
    alerts = predict(rows, bundle, manifest, domain)
    drift = {'features':[], 'method':'Fraction beyond training mean +/- 3 standard deviations; diagnostic only'}
    if rows:
        z = np.abs((matrix(rows)-bundle['scaler'].mean_)/np.maximum(bundle['scaler'].scale_,1e-6))
        drift['features'] = [{'feature':FEATURES[j],'outlier_fraction':round(float((z[:,j]>3).mean()),4)} for j in range(len(FEATURES)) if (z[:,j]>3).mean()>.2]
    with db:
        db.execute("DELETE FROM alerts")
        db.executemany("INSERT INTO alerts VALUES (?,?,?)", [(a["address"], a["priority"], canonical(a)) for a in alerts])
        set_meta(db, "model", manifest)
        set_meta(db, "scored", True)
        set_meta(db, "scored_at", datetime.now(timezone.utc).isoformat())
        set_meta(db,'drift',drift)
        audit(db, {"event": "scored", "model_sha256": manifest["artifact_sha256"], "address_profiles": len(alerts),
                   "alert_digest": __import__("hashlib").sha256(canonical(alerts).encode()).hexdigest()})
    db.close()
    return {"profiles": len(alerts), "high_priority": int(sum(a['priority_band']=='High' for a in alerts))}
