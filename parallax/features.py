"""Address-level features. Repeated relay observations never duplicate money flows."""
import json
import math
from collections import Counter
from datetime import datetime
from statistics import mean, median, pstdev

import numpy as np
from .intelligence import context, enrich_profile

CHAIN_FEATURES = ["log_tx_count", "log_total_btc", "log_mean_btc", "amount_variation",
                  "max_fan_out", "max_fan_in", "log_median_gap_seconds", "mean_fee_ratio",
                  "equal_output_fraction"]
NETWORK_FEATURES = ["mean_observations_per_tx", "mean_source_ips_per_tx", "log_relay_span_seconds",
                    "network_coverage", "mean_source_transaction_degree"]
EXTRA_FEATURES = ['in_degree','out_degree','seed_hop_distance','seed_evidence_available','round_output_ratio',
                  'interval_entropy','hour_concentration','fee_rate_cv','fee_rate_available','relay_associations']
CHAIN_FEATURES += EXTRA_FEATURES[:-1]
FEATURES = CHAIN_FEATURES + NETWORK_FEATURES + EXTRA_FEATURES[-1:]


def build_features(db):
    ctx = context(db)
    addresses = [r[0] for r in db.execute("SELECT DISTINCT address FROM flows WHERE direction='input' ORDER BY address")]
    source_degree = dict(db.execute("SELECT src_ip,COUNT(DISTINCT txid) FROM observations WHERE src_ip IS NOT NULL GROUP BY src_ip"))
    fan = {r["txid"]: dict(r) for r in db.execute("""SELECT txid,
             SUM(direction='input') AS inputs, SUM(direction='output') AS outputs
             FROM flows GROUP BY txid""")}
    result = []
    for address in addresses:
        txs = list(db.execute("""SELECT t.* FROM transactions t JOIN
           (SELECT DISTINCT txid FROM flows WHERE address=? AND direction='input') f ON f.txid=t.txid
           ORDER BY t.first_seen,t.txid""", (address,)))
        amounts, fees, equal = [], [], []
        obs_per_tx, ips_per_tx, spans, degrees, network_count = [], [], [], [], 0
        observation_count, geo_count, missing_scripts = 0, 0, 0
        source_refs = []
        for t in txs:
            chain = json.loads(t["chain_json"])
            value = sum(chain["output_sats"]) / 1e8
            amounts.append(value)
            fees.append(chain["fee_sats"] / max(1, sum(chain["input_sats"])))
            counter = Counter(chain["output_sats"])
            equal.append(int(len(chain["output_sats"]) >= 3 and max(counter.values()) >= 3))
            missing_scripts += int(t["script_type"] is None)
            observations = list(db.execute("SELECT * FROM observations WHERE txid=? ORDER BY timestamp", (t["txid"],)))
            present = [o for o in observations if o["src_ip"]]
            network_count += bool(present)
            obs_per_tx.append(len(present))
            ips_per_tx.append(len({o["src_ip"] for o in present}))
            seconds = [datetime.fromisoformat(o["timestamp"]).timestamp() for o in present]
            spans.append(max(seconds) - min(seconds) if len(seconds) > 1 else 0)
            degrees.extend(source_degree[o["src_ip"]] for o in present)
            observation_count += len(observations)
            geo_count += sum(o["geo_country"] is not None and o["asn"] is not None for o in observations)
            source_refs.extend({"source_sha256": o["source_hash"], "row": o["source_row"], "observation_id": o["id"], "txid": t["txid"]} for o in observations)
        times = [datetime.fromisoformat(t["first_seen"]).timestamp() for t in txs]
        gaps = [b - a for a, b in zip(times, times[1:])]
        gap = median(gaps) if gaps else 86400
        count = len(txs)
        values = [math.log1p(count), math.log1p(sum(amounts)), math.log1p(mean(amounts)),
                  pstdev(amounts) / max(mean(amounts), 1e-12),
                  max(fan[t["txid"]]["outputs"] for t in txs), max(fan[t["txid"]]["inputs"] for t in txs),
                  math.log1p(gap), mean(fees), mean(equal), mean(obs_per_tx), mean(ips_per_tx),
                  math.log1p(mean(spans)), network_count / count, math.log1p(mean(degrees)) if degrees else 0]
        rules = []
        if values[4] >= 8:
            rules.append({"name": "High fan-out", "strength": 0.55, "reason": f"At least one transaction has {int(values[4])} outputs; batching is a benign alternative."})
        if count >= 5 and gap <= 90:
            rules.append({"name": "Rapid repeated spending", "strength": 0.65, "reason": f"{count} transactions with median observed gap {gap:.0f}s; automated services can behave similarly."})
        if mean(equal) >= 0.5:
            rules.append({"name": "Repeated equal outputs", "strength": 0.35, "reason": "At least half of transactions have 3+ equal outputs; collaborative transactions are not proof of illicit activity."})
        coverage = network_count / count
        # Coverage is explicitly an evidence-quality index, not P(illicit).
        quality = round(100 * (0.65 + 0.25 * coverage + 0.10 * (1 - missing_scripts / count)), 1)
        caveats = ["Network endpoints may be relays, shared infrastructure, or NAT; no ownership attribution.",
                   "Anomaly scores measure unusual behavior, not criminality."]
        if coverage < 1:
            caveats.append("Network metadata is incomplete; zero-filled network features are accompanied by a coverage feature.")
        if geo_count < observation_count:
            caveats.append("Country/ASN enrichment is partly or wholly unavailable; no geolocation is inferred.")
        if max(degrees, default=0) > 20:
            caveats.append("A source IP relays many transactions; a shared relay is a plausible alternative explanation.")
        base_names = CHAIN_FEATURES[:9] + NETWORK_FEATURES
        profile = {"address": address, "features": dict(zip(base_names, values)), "vector": values,
                       "tx_count": count, "total_btc": round(sum(amounts), 8), "first_seen": txs[0]["first_seen"],
                       "last_seen": txs[-1]["first_seen"], "txids": [t["txid"] for t in txs],
                       "rules": rules, "rule_score": max((r["strength"] for r in rules), default=0),
                       "evidence_quality": quality, "network_coverage": round(coverage, 4),
                       "geo_coverage": round(geo_count / max(observation_count, 1), 4),
                       "evidence": source_refs, "caveats": caveats}
        from .analysis import changepoints
        profile["behavioral_drift"] = changepoints(txs)
        for rule in rules:
            rule.setdefault("txids", profile["txids"])
        result.append(enrich_profile(profile,ctx,txs))
    from .analysis import enrich
    return enrich(result, db, ctx)


def matrix(rows, names=FEATURES):
    return np.asarray([[r["features"][name] for name in names] for r in rows], dtype=float)
