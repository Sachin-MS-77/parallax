"""Frozen-test evaluation; fixed thresholds, no tuning on held-out results."""
import json
from pathlib import Path

import numpy as np
from sklearn.metrics import average_precision_score, brier_score_loss, precision_score, recall_score

from .features import build_features
from .model import load_model, predict
from .storage import connect, digest, file_hash, get_meta, set_meta


def metrics(y, scores, threshold, k=20):
    y, scores = np.asarray(y), np.asarray(scores)
    selected = scores >= threshold
    order = np.argsort(-scores, kind="stable")[:min(k, len(y))]
    negative = y == 0
    positives = int(y.sum())
    return {"precision_at_20": float(y[order].mean()), "k_used": len(order),
            "precision": float(precision_score(y, selected, zero_division=0)),
            "recall": float(recall_score(y, selected, zero_division=0)),
            "false_positive_rate": float(selected[negative].mean()) if negative.any() else None,
            "average_precision": float(average_precision_score(y, scores)) if positives else None,
            "threshold": threshold, "alerts": int(selected.sum()), "positives": positives, "profiles": len(y)}


def evaluate(db_path, model_dir, labels_path, output):
    truth = json.loads(Path(labels_path).read_text())
    if truth.get("split") != "test" or truth.get("domain") != "synthetic":
        raise ValueError("Evaluation requires a held-out synthetic test label file")
    bundle, manifest = load_model(model_dir)
    db = connect(db_path)
    rows = build_features(db)
    sources = [r[0] for r in db.execute("SELECT hash FROM sources")]
    used = manifest["training_sources"] + ((manifest["calibration"] or {}).get("source_hashes", []))
    used += manifest.get('feedback',{}).get('sources',[])
    if set(sources) & set(used):
        db.close()
        raise ValueError("Test source overlaps training or calibration")
    used_addresses = manifest["training_address_hashes"] + ((manifest["calibration"] or {}).get("address_hashes", []))
    used_addresses += manifest.get('feedback',{}).get('address_hashes',[])
    if {digest(r["address"]) for r in rows} & set(used_addresses):
        db.close()
        raise ValueError("Test addresses overlap training or calibration")
    boundary = max(manifest["training_end_time"], (manifest["calibration"] or {}).get("end_time", ""),manifest.get('feedback',{}).get('end_time',''))
    if not rows or min(r["first_seen"] for r in rows) <= boundary:
        db.close()
        raise ValueError("Test must follow training and calibration time windows")
    if set(r["address"] for r in rows) != set(truth["labels"]):
        db.close()
        raise ValueError("Test labels must exactly match the input-address profiles")
    alerts = predict(rows, bundle, manifest, "synthetic", explanations=False)
    # Stable address order prevents fused priority from breaking baseline ties favorably.
    alerts.sort(key=lambda a: a["address"])
    y = [truth["labels"][a["address"]]["label"] for a in alerts]
    baselines = {"rules_only": ([a["rule_score"] for a in alerts], 0.5),
                 "chain_only_ml": ([a["chain_percentile"] / 100 for a in alerts], 0.95),
                 "fused_ml": ([a["model_percentile"] / 100 for a in alerts], 0.95),
                 "fused_priority": ([a["priority"] / 100 for a in alerts], manifest.get('priority_threshold',80)/100)}
    if all(a.get('graph_score') is not None for a in alerts):
        baselines['graphsage']=([a['graph_score'] for a in alerts],.5)
    report = {"scope": "Held-out synthetic scenarios only; not real-world detection accuracy", "split": "test",
              "model_sha256": manifest["artifact_sha256"], "labels_sha256": file_hash(labels_path),
              "test_source_hashes": sources, "threshold_policy":manifest.get('threshold_policy'),
              "baselines": {name: metrics(y, scores, threshold) for name, (scores, threshold) in baselines.items()}}
    report["per_scenario"] = {}
    for scenario in sorted({v["scenario"] for v in truth["labels"].values()}):
        idx = [i for i, a in enumerate(alerts) if truth["labels"][a["address"]]["scenario"] == scenario]
        # Positive scenarios are paired with benign controls for meaningful precision/FPR.
        if any(y[i] for i in idx): idx += [i for i in range(len(y)) if y[i]==0]
        report["per_scenario"][scenario] = metrics([y[i] for i in idx], [alerts[i]["priority"] / 100 for i in idx], manifest.get('priority_threshold',80)/100)
    probabilities = [a["synthetic_probability"] for a in alerts]
    if all(p is not None for p in probabilities):
        report["calibration"] = {"brier_score": float(brier_score_loss(y, probabilities)), "domain": "synthetic", "bins": []}
        for lower in np.linspace(0, 0.8, 5):
            idx = [i for i, p in enumerate(probabilities) if lower <= p < lower + 0.2 + (1e-9 if lower == 0.8 else 0)]
            if idx:
                report["calibration"]["bins"].append({"lower": float(lower), "count": len(idx),
                    "mean_predicted": float(np.mean([probabilities[i] for i in idx])), "observed_rate": float(np.mean([y[i] for i in idx]))})
    report["limitations"] = ["Synthetic data is generated by the same project; independent external validation remains necessary.",
                               "Entities and time periods are disjoint; scenario families recur across calibration and test.",
                               "Performance must not be presented as operational accuracy or probability of criminality.",
                               "Seed proximity is bounded graph distance, not an assertion that funds or owners are illicit."]
    with db:
        set_meta(db, "evaluation", report)
    db.close()
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(json.dumps(report, indent=2))
    return report
