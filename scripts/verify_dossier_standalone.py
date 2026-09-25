#!/usr/bin/env python3
"""Independent verification: stdlib + cryptography only. No PARALLAX imports.

Usage: python verify_dossier_standalone.py case.zip original-audit.jsonl --trusted-key public-key.txt
Supply the separately retained original audit export and trusted public key.
"""
import argparse
import base64
import hashlib
import json
import zipfile
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",",":"), ensure_ascii=False, default=str).encode()


def verify(archive, original_log, trusted_key):
    def require(condition, message):
        if not condition: raise ValueError(message)
    with zipfile.ZipFile(archive) as z:
        names=z.namelist()
        require(len(names)==len(set(names)), "Duplicate archive member")
        public=bytes.fromhex(Path(trusted_key).read_text().strip())
        require(z.read("public-key.txt").decode().strip()==public.hex(), "Untrusted signer")
        key=Ed25519PublicKey.from_public_bytes(public)
        manifest_bytes=z.read("manifest.json")
        key.verify(base64.b64decode(z.read("signature.txt"),validate=True),manifest_bytes)
        manifest=json.loads(manifest_bytes)
        expected={"case.json","report.html","report.pdf","report.pdf.sig","subgraph.svg","audit.jsonl","scoring-snapshot.json"}
        require(set(manifest["files"])==expected,"Unexpected manifest members")
        require(set(names)==expected|{"manifest.json","signature.txt","public-key.txt"},"Unexpected archive members")
        for name,hashed in manifest["files"].items():
            require(hashlib.sha256(z.read(name)).hexdigest()==hashed,"File hash mismatch: "+name)
        key.verify(base64.b64decode(z.read("report.pdf.sig"),validate=True),z.read("report.pdf"))
        case=json.loads(z.read("case.json"))
        anchor=case["audit_anchor"]; previous="0"*64; accepted={}; latest_score=None; anchor_seen=False
        embedded=z.read("audit.jsonl").splitlines()
        count=0
        with Path(original_log).open("rb") as f:
            for count,line in enumerate(f,1):
                r=json.loads(line)
                require(r["seq"]==count and r["previous_hash"]==previous,"Broken sequence/link")
                current=hashlib.sha256((previous+r["payload"]).encode()).hexdigest()
                require(r["hash"]==current,"Invalid audit hash")
                previous=current
                if count<=anchor["entries"]:
                    require(count<=len(embedded) and json.loads(embedded[count-1])==r,"Original log differs from signed snapshot")
                    event=json.loads(r["payload"])
                    if event.get("event")=="accepted": accepted[event["observation_id"]]=event
                    if event.get("event")=="scored": latest_score=event["alert_digest"]
                if count==anchor["entries"]:
                    require(current==anchor["head"],"Anchor mismatch");anchor_seen=True
        require(anchor_seen and len(embedded)==anchor["entries"],"Log truncated or signed anchor missing")
        snapshot=json.loads(z.read("scoring-snapshot.json"))
        require(hashlib.sha256(canonical(snapshot)).hexdigest()==latest_score,"Score snapshot differs from original audit")
        alert_map={a["address"]:a for a in snapshot}
        require(case["alert"] in case["cluster"]["alerts"],"Selected alert differs from cluster evidence")
        require(set(case["cluster"]["members"])==set(case["alert"]["entity_members"]),"Altered cluster membership")
        for a in case["cluster"]["alerts"]:
            original=alert_map.get(a["address"])
            require(original is not None,"Cluster alert absent from original scoring")
            # Reviews are subsequent audit events; scoring fields must remain identical.
            require({k:v for k,v in a.items() if k not in ("reviews","status")}==
                    {k:v for k,v in original.items() if k not in ("reviews","status")},"Altered cluster alert")
        transactions={t["txid"]:t for t in case["transactions"]}
        for row in case["observations"]:
            proof=accepted.get(row["id"]);body=json.loads(row["record_json"])
            require(proof is not None,"Unaudited observation")
            require(hashlib.sha256(canonical(body)).hexdigest()==proof["normalized_sha256"],"Altered observation")
            require(row["source_hash"]==proof["source"] and row["source_row"]==proof["row"],"Altered provenance")
            for field in ("txid","timestamp","src_ip","dst_ip","src_port","dst_port","geo_country","asn","geo_source"):
                require(row[field]==body[field],"Altered observation column")
            fields=("txid","input_addresses","output_addresses","input_sats","output_sats","fee_sats","script_type","vsize")
            chain={k:body[k] for k in fields if k in body}
            require(json.loads(transactions[row["txid"]]["chain_json"])==chain,"Altered transaction")
        require(set(transactions)=={r["txid"] for r in case["observations"]},"Transaction without observation evidence")
        require(case["cluster"]["unique_transactions"]==len(transactions),"Incorrect cluster transaction count")
    return {"valid":True,"original_log_entries":count,"signed_anchor":anchor["head"],
            "cluster_members":len(case["cluster"]["members"]),"observations":len(case["observations"]),
            "scope":"Signatures, original hash-chain prefix, score snapshot and normalized records checked independently"}


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("dossier");p.add_argument("original_log");p.add_argument("--trusted-key",required=True)
    args=p.parse_args()
    try: print(json.dumps(verify(args.dossier,args.original_log,args.trusted_key),indent=2))
    except Exception as e:
        print(json.dumps({"valid":False,"error":str(e) or type(e).__name__}));raise SystemExit(1)
