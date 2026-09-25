"""Evidence-derived temporal drift, chronological haircut exposure and endpoints."""
import csv
import json
import math
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path

import numpy as np
import ruptures as rpt
from .storage import audit, canonical, file_hash, get_meta, set_meta


def config(db=None):
    value = json.loads(Path(__file__).with_name("fracture.json").read_text())
    if db is not None:
        value = get_meta(db, "fracture_config", value)
    w = value["weights"]
    expected = {"taint", "behavioral_link", "timing", "address_reuse", "network_exposure"}
    if set(w) != expected or any(not math.isfinite(v) or v < 0 for v in w.values()) or abs(sum(w.values())-1)>1e-6:
        raise ValueError("Fracture weights must be finite, nonnegative and sum to one")
    if not 0 < value["decay"] <= 1:
        raise ValueError("Taint decay must be in (0,1]")
    return value


def changepoints(records):
    """PELT over a wallet's time-ordered log amount, gap, fan-out and fee rate."""
    base = {"method": "ruptures.Pelt/l2", "changes": [], "score": 0.0,
            "minimum_transactions": 8, "observations": len(records)}
    if len(records) < 8:
        return {**base, "status": "insufficient_history"}
    stamps = [datetime.fromisoformat(t["first_seen"]).timestamp() for t in records]
    gaps = np.diff(stamps)
    signal = []
    for i, t in enumerate(records):
        c = json.loads(t["chain_json"])
        signal.append([math.log1p(sum(c["output_sats"])/1e8),
                       math.log1p(gaps[i-1] if i else float(np.median(gaps))),
                       math.log1p(len(c["output_addresses"])),
                       math.log1p(c["fee_sats"]/c["vsize"]) if c.get("vsize") else 0])
    x = np.asarray(signal)
    x = (x-x.mean(0))/np.maximum(x.std(0), 0.1)
    cuts = rpt.Pelt(model="l2", min_size=3, jump=1).fit(x).predict(pen=4*math.log(len(x)))
    start = 0
    for i, end in enumerate(cuts[:-1]):
        nxt = cuts[i+1]
        shift = float(np.linalg.norm(x[start:end].mean(0)-x[end:nxt].mean(0)))
        base["changes"].append({"index": end, "timestamp": records[end]["first_seen"],
                                "txid": records[end]["txid"], "standardized_shift": round(shift, 4),
                                "before_txids": [r["txid"] for r in records[start:end]],
                                "after_txids": [r["txid"] for r in records[end:nxt]]})
        start = end
    base["score"] = min(1., max((c["standardized_shift"]/4 for c in base["changes"]), default=0))
    return {**base, "status": "change_detected" if base["changes"] else "stable",
            "caveat": "A behavior change can reflect legitimate operational changes."}


def haircut(db, decay=.9):
    """Proportional address-account approximation, with explicit incomplete-UTXO scope.

    Consume observed balances proportionally. Unseen funding is untainted/unknown;
    seeds tag declared funds at the seed, not the identities of downstream owners.
    Per-hop decay reduces exposure, never creates value. Fee share exits the ledger.
    """
    seeds = {s["address"]: s for s in get_meta(db, "seed_addresses", [])}
    balance = defaultdict(float)
    tainted = defaultdict(lambda: defaultdict(float))
    trails = defaultdict(dict)
    received, exposed = defaultdict(float), defaultdict(float)
    out = {}
    for t in db.execute("SELECT * FROM transactions ORDER BY first_seen,txid"):
        c = json.loads(t["chain_json"]); parts = defaultdict(float); proofs = {}
        for a, amount in zip(c["input_addresses"], c["input_sats"]):
            if a in seeds:
                parts[a] += amount
                proofs[a] = {"seed": a, "source": seeds[a]["source"], "txids": [], "hops": 0}
                out[a] = {"fraction": 1., "seed": True, "sources": [proofs[a]], "traced_received_sats": 0}
            else:
                fraction = min(1., amount/max(balance[a], amount, 1))
                for s, value in list(tainted[a].items()):
                    taken = value*fraction
                    parts[s] += taken
                    tainted[a][s] -= taken
                    if taken > 0 and s in trails[a]: proofs[s] = trails[a][s]
            balance[a] = max(0., balance[a]-amount)
        total = sum(c["input_sats"])
        for a, amount in zip(c["output_addresses"], c["output_sats"]):
            balance[a] += amount; received[a] += amount
            for s, value in parts.items():
                allocation = min(amount, amount*value/max(total, 1)*decay)
                tainted[a][s] += allocation; exposed[a] += allocation
                if allocation > 0 and s in proofs:
                    proof = {**proofs[s], "txids": proofs[s]["txids"]+[t["txid"]],
                             "hops": proofs[s]["hops"]+1}
                    # Retain a supporting shortest path, not a claim all value used it.
                    if s not in trails[a] or proof["hops"] < trails[a][s]["hops"]:
                        trails[a][s] = proof
            if a not in seeds:
                out[a] = {"fraction": min(1., exposed[a]/max(received[a],1)),
                          "traced_received_sats": round(exposed[a], 4), "observed_received_sats": received[a],
                          "sources": list(trails[a].values()), "seed": False}
    for a, item in out.items():
        item["available"] = bool(seeds)
        item["method"] = "chronological proportional haircut / address-account approximation"
        item["decay"] = decay
        item["caveat"] = "No UTXO outpoints supplied: proportional address accounting is an estimate, not exact coin tracing."
    return out


def endpoints(address, ctx, known, limit=6):
    queue = deque([(address, [])]); visited = {address}; found = []
    while queue:
        current, path = queue.popleft()
        if len(path) >= limit: continue
        for nxt in sorted(ctx["outgoing"].get(current, ())):
            if nxt in visited: continue
            visited.add(nxt); route = path+[nxt]
            degree = len(ctx["incoming"].get(nxt, ()))
            terminal = not ctx["outgoing"].get(nxt)
            match = known.get(nxt)
            if match or (terminal and degree >= 3):
                found.append({"address": nxt, "hops": len(route), "path": [address]+route,
                              "observed_terminal": terminal, "distinct_funders": degree,
                              "reference": match, "score": .9 if match else min(.75, .3+degree*.02),
                              "basis": "local exchange reference" if match else "observed terminal with multiple distinct funders",
                              "label": "Likely cash-out target (unverified)",
                              "caveat": "Incomplete graphs and merchant consolidation can look like off-ramps. No KYC or subpoena conclusion."})
            queue.append((nxt, route))
    return sorted(found, key=lambda x:(-x["score"],x["address"]))[:5]


def enrich(rows, db, ctx):
    settings = config(db)
    exposures = haircut(db, settings["decay"])
    known = {s["address"]: s for s in get_meta(db, "exchange_addresses", [])}
    for row in rows:
        row["taint"] = exposures.get(row["address"], {"available": bool(get_meta(db,"seed_addresses",[])),
                                    "fraction": 0., "sources": [], "traced_received_sats": 0})
        row["cashout_targets"] = endpoints(row["address"], ctx, known)
        row["fracture_config"] = settings
    return rows


def case_note(alert):
    notes = [f"Address {alert['address']} has {alert['tx_count']} observed spending transactions.",
             f"Fracture Index {alert['priority']:.2f}/100 ({alert['confidence_band']} score band)."]
    taint = alert["taint"]
    if taint.get("sources"):
        references = "; ".join(sorted({p["source"] for p in taint["sources"]}))
        hops = sorted({p["hops"] for p in taint["sources"]})
        notes.append(f"Estimated decayed seed exposure: {taint['fraction']:.1%}; supporting path hop counts {hops}; references: {references}. This is proportional address accounting, not exact UTXO tracing.")
    elif not taint["available"]:
        notes.append("No seed reference set was supplied; taint evidence is unavailable.")
    if alert["behavioral_drift"]["changes"]:
        notes.append("Behavior changes detected at "+", ".join(c["timestamp"] for c in alert["behavioral_drift"]["changes"])+".")
    if alert["rules"]: notes.append("Observed patterns: "+", ".join(r["name"] for r in alert["rules"])+".")
    if alert["cashout_targets"]:
        notes.append("Unverified cash-out candidates: "+", ".join(t["address"] for t in alert["cashout_targets"])+".")
    else: notes.append("No supported cash-out candidate found within the bounded downstream search.")
    notes.append("Relay associations and pattern matches do not establish ownership or criminality.")
    return " ".join(notes)


def import_references(db_path, path, kind="seeds"):
    from .storage import connect
    path = Path(path)
    if path.suffix.lower() == ".csv":
        with path.open(newline="") as f: rows = list(csv.DictReader(f))
    else: rows = json.loads(path.read_text())
    if not isinstance(rows,list) or any(not r.get("address") or not r.get("source") for r in rows):
        raise ValueError("References require address and source fields")
    for r in rows:
        if r.get("currency", "XBT") not in ("BTC","XBT"):
            raise ValueError("Only Bitcoin reference addresses are supported")
        r["file_sha256"] = file_hash(path)
    db = connect(db_path)
    with db:
        set_meta(db, "seed_addresses" if kind=="seeds" else "exchange_addresses", rows)
        set_meta(db, "scored", False); set_meta(db, "evaluation", None)
        db.execute("DELETE FROM alerts")
        audit(db, {"event": "reference_update", "kind": kind, "references": rows, "file_sha256": file_hash(path)})
    db.close()
    return {"imported": len(rows), "rescore_required": True}
