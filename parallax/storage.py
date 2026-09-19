"""SQLite storage and a verifiable, locally anchored audit trail."""
import hashlib
import json
import sqlite3
from pathlib import Path


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
 hash TEXT PRIMARY KEY, name TEXT NOT NULL, stored_path TEXT NOT NULL, format TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS transactions (
 txid TEXT PRIMARY KEY, chain_json TEXT NOT NULL, first_seen TEXT NOT NULL,
 fee_sats INTEGER, script_type TEXT);
CREATE TABLE IF NOT EXISTS flows (
 txid TEXT NOT NULL, direction TEXT NOT NULL, ordinal INTEGER NOT NULL,
 address TEXT NOT NULL, amount_sats INTEGER NOT NULL,
 PRIMARY KEY(txid,direction,ordinal), FOREIGN KEY(txid) REFERENCES transactions(txid));
CREATE INDEX IF NOT EXISTS flows_address ON flows(address);
CREATE TABLE IF NOT EXISTS observations (
 id TEXT PRIMARY KEY, txid TEXT NOT NULL, timestamp TEXT NOT NULL,
 src_ip TEXT, dst_ip TEXT, src_port INTEGER, dst_port INTEGER,
 geo_country TEXT, asn INTEGER, geo_source TEXT, source_hash TEXT NOT NULL,
 source_row INTEGER NOT NULL, record_json TEXT NOT NULL,
 FOREIGN KEY(txid) REFERENCES transactions(txid));
CREATE INDEX IF NOT EXISTS obs_tx ON observations(txid);
CREATE INDEX IF NOT EXISTS obs_src ON observations(src_ip);
CREATE TABLE IF NOT EXISTS quarantine (
 id INTEGER PRIMARY KEY, source_hash TEXT NOT NULL, source_row INTEGER NOT NULL,
 error TEXT NOT NULL, raw_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit (
 seq INTEGER PRIMARY KEY, previous_hash TEXT NOT NULL, payload TEXT NOT NULL, hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS alerts (
 address TEXT PRIMARY KEY, priority REAL NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reviews (
 id INTEGER PRIMARY KEY, address TEXT NOT NULL, status TEXT NOT NULL,
 reason TEXT NOT NULL, timestamp TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def connect(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript(SCHEMA)
    return db


def audit(db, payload):
    last = db.execute("SELECT hash FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
    previous = last[0] if last else "0" * 64
    body = canonical(payload)
    hashed = hashlib.sha256((previous + body).encode()).hexdigest()
    db.execute("INSERT INTO audit(previous_hash,payload,hash) VALUES (?,?,?)", (previous, body, hashed))
    return hashed


def verify_audit(db, expected_head=None):
    previous, count = "0" * 64, 0
    for row in db.execute("SELECT * FROM audit ORDER BY seq"):
        count += 1
        expected = hashlib.sha256((previous + row["payload"]).encode()).hexdigest()
        if row["seq"] != count or row["previous_hash"] != previous or row["hash"] != expected:
            return {"valid": False, "failed_at": row["seq"], "entries": count}
        previous = row["hash"]
    return {"valid": expected_head is None or previous == expected_head,
            "head": previous, "entries": count, "externally_anchored": expected_head is not None}


def verify_state(db, expected_head=None):
    """Check the audit chain plus materialized records and latest scoring snapshot."""
    result = verify_audit(db, expected_head)
    if not result["valid"]:
        return result
    accepted, score_digest = {}, None
    for entry in db.execute("SELECT payload FROM audit ORDER BY seq"):
        event = json.loads(entry[0])
        if event.get("event") == "accepted":
            accepted[event["observation_id"]] = event
        if event.get("event") == "scored":
            score_digest = event["alert_digest"]
    error = None
    for row in db.execute("SELECT * FROM observations"):
        body = json.loads(row["record_json"])
        proof = accepted.pop(row["id"], None)
        if not proof or digest(body) != proof["normalized_sha256"] or row["source_hash"] != proof["source"] or row["source_row"] != proof["row"]:
            error = "Observation provenance or content mismatch"
            break
        for name in ("txid", "timestamp", "src_ip", "dst_ip", "src_port", "dst_port", "geo_country", "asn", "geo_source"):
            if row[name] != body[name]:
                error = "Observation columns disagree with preserved record"
                break
        chain = {k: body[k] for k in ("txid", "input_addresses", "output_addresses", "input_sats", "output_sats", "fee_sats", "script_type")}
        if 'vsize' in body: chain['vsize'] = body['vsize']
        tx = db.execute("SELECT * FROM transactions WHERE txid=?", (row["txid"],)).fetchone()
        if not tx or tx["chain_json"] != canonical(chain) or tx["fee_sats"] != body["fee_sats"] or tx["script_type"] != body["script_type"]:
            error = "Transaction content mismatch"
            break
    if accepted and not error:
        error = "Audited observations are missing"
    for tx in db.execute("SELECT * FROM transactions"):
        body = json.loads(tx["chain_json"])
        for direction in ("input", "output"):
            flows = [(r[0], r[1]) for r in db.execute("SELECT address,amount_sats FROM flows WHERE txid=? AND direction=? ORDER BY ordinal", (tx["txid"], direction))]
            if flows != list(zip(body[direction + "_addresses"], body[direction + "_sats"])):
                error = "Flow table disagrees with transaction evidence"
        earliest = db.execute("SELECT MIN(timestamp) FROM observations WHERE txid=?", (tx["txid"],)).fetchone()[0]
        if tx["first_seen"] != earliest:
            error = "Transaction first_seen disagrees with observations"
    if get_meta(db, "scored", False) and score_digest:
        alerts = [json.loads(r[0]) for r in db.execute("SELECT payload FROM alerts ORDER BY priority DESC,address")]
        if digest(alerts) != score_digest:
            error = "Scored alert snapshot has changed"
        if any(a["address"] != r["address"] or a["priority"] != r["priority"] for a, r in zip(alerts, db.execute("SELECT address,priority FROM alerts ORDER BY priority DESC,address"))):
            error = "Alert index disagrees with scoring snapshot"
    result.update({"valid": error is None, "materialized_state_checked": True})
    if error:
        result["error"] = error
    return result


def set_meta(db, key, value):
    db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, canonical(value)))


def get_meta(db, key, default=None):
    row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else default
