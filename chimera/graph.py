"""Bounded evidence graph. Edges explicitly distinguish observation and flow."""
from collections import defaultdict
from .intelligence import context


def graph(db, address, layer="fused", limit=80):
    if layer not in ("fused", "chain", "network"):
        raise ValueError("Unknown layer")
    txids = [r[0] for r in db.execute("SELECT DISTINCT txid FROM flows WHERE address=? ORDER BY txid LIMIT ?", (address, limit))]
    total_txs = db.execute("SELECT COUNT(DISTINCT txid) FROM flows WHERE address=?", (address,)).fetchone()[0]
    nodes, edges = {}, []
    total_flows, shown_flows, total_obs, shown_obs = 0, 0, 0, 0
    def node(identifier, kind, label, **extra):
        nodes[identifier] = {"id": identifier, "kind": kind, "label": label, **extra}
    node("address:" + address, "address", address, selected=True)
    ctx = context(db)
    eid = ctx['membership'].get(address)
    if eid and layer != 'network':
        members=next(e['members'] for e in ctx['entities'] if e['id']==eid)
        node(eid,'wallet',eid, hypothesis=True)
        for member in members[:20]:
            node('address:'+member,'address',member,selected=member==address)
            edges.append({'source':eid,'target':'address:'+member,'kind':'candidate_member','certainty':'heuristic_not_verified'})
    for txid in txids:
        tid = "tx:" + txid
        node(tid, "transaction", txid, highlighted=txid in ctx['peel'] or txid in ctx['mixers'])
        if layer in ("fused", "chain"):
            total_flows += db.execute("SELECT COUNT(*) FROM flows WHERE txid=?", (txid,)).fetchone()[0]
            for f in db.execute("SELECT * FROM flows WHERE txid=? ORDER BY (address=?) DESC,direction,ordinal LIMIT 40", (txid, address)):
                aid = "address:" + f["address"]
                node(aid, "address", f["address"], selected=f["address"] == address)
                source, target = (aid, tid) if f["direction"] == "input" else (tid, aid)
                edges.append({"source": source, "target": target, "kind": f["direction"], "amount_sats": f["amount_sats"], "certainty": "reported_transaction_metadata"})
                shown_flows += 1
        else:
            edges.append({"source": "address:" + address, "target": tid, "kind": "transaction_context", "certainty": "reported_transaction_metadata"})
        total_obs += db.execute("SELECT COUNT(*) FROM observations WHERE txid=?", (txid,)).fetchone()[0]
        if layer in ("fused", "network"):
            groups = defaultdict(list)
            for o in db.execute("SELECT * FROM observations WHERE txid=? ORDER BY timestamp LIMIT 60", (txid,)):
                shown_obs += 1
                for role in ("src_ip", "dst_ip"):
                    if o[role]:
                        groups[(o[role], role)].append({"timestamp": o["timestamp"], "port": o[role.replace("ip", "port")],
                                                       "observation_id": o["id"], "source_sha256": o["source_hash"], "row": o["source_row"]})
            for (ip, role), observations in groups.items():
                iid = "ip:" + ip
                node(iid, "ip", ip)
                edges.append({"source": iid, "target": tid, "kind": "observed_source" if role == "src_ip" else "observed_destination",
                              "certainty": "observed_relay_only", "observations": observations,
                              "warning": "Does not establish address ownership or transaction origin"})
    if layer == 'fused':
        for a in [a for a in ctx['associations'] if address in (a['source'],a['target'])][:20]:
            for key in ('source','target'): node('address:'+a[key],'address',a[key],selected=a[key]==address)
            edges.append({**a,'source':'address:'+a['source'],'target':'address:'+a['target'],
                          'kind':'relay_association','certainty':'weak_no_ownership_claim'})
        for a in [a for a in ctx['change_candidates'] if address in (a['source'],a['target'])][:10]:
            for key in ('source','target'): node('address:'+a[key],'address',a[key],selected=a[key]==address)
            edges.append({**a,'source':'address:'+a['source'],'target':'address:'+a['target'],'kind':'change_candidate'})
    return {"nodes": list(nodes.values()), "edges": edges, "layer": layer,
            "suppressed_shared_relays":ctx['suppressed_hubs'],
            "truncated": total_txs > len(txids) or total_flows > shown_flows or (layer != "chain" and total_obs > shown_obs),
            "total_transactions": total_txs, "shown_transactions": len(txids),
            "ownership_claims": 0, "limits": {"transactions": limit, "flows_per_tx": 40, "observations_per_tx": 60}}
