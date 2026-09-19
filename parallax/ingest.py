"""Streaming parsing, strict monetary validation, and source preservation."""
import csv
import ipaddress
import json
import re
import shutil
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

import ijson
from defusedxml.ElementTree import iterparse

from .storage import audit, canonical, connect, digest, file_hash, set_meta

ALIASES = {"time": "timestamp", "transaction_id": "txid", "source_ip": "src_ip",
           "destination_ip": "dst_ip", "source_port": "src_port", "destination_port": "dst_port",
           "input_addresses[]": "input_addresses", "output_addresses[]": "output_addresses",
           "input_amounts[]": "input_amounts", "output_amounts[]": "output_amounts",
           "country": "geo_country"}
KNOWN_FIELDS = {'timestamp','txid','input_addresses','output_addresses','input_amounts','output_amounts',
                'src_ip','dst_ip','src_port','dst_port','fee','script_type','geo_country','asn','vsize'}


def records(path):
    suffix = Path(path).suffix.lower()
    if suffix == ".csv":
        with open(path, encoding="utf-8-sig", newline="") as f:
            yield from csv.DictReader(f)
    elif suffix in (".jsonl", ".ndjson"):
        with open(path, encoding="utf-8-sig") as f:
            for line in f:
                if not line.strip():
                    yield {"__parse_error__": "Blank JSONL record"}
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as e:
                    yield {"__parse_error__": str(e), "__raw_line__": line.rstrip("\n")}
    elif suffix == ".json":
        with open(path, "rb") as f:
            # Supported containers are a top-level array or {"records": [...]}.
            first = b""
            while not first.strip():
                first = f.read(1)
                if not first:
                    raise ValueError("Empty JSON file")
            f.seek(0)
            yield from ijson.items(f, "item" if first == b"[" else "records.item")
    elif suffix == ".xml":
        for _, element in iterparse(path, events=("end",), forbid_dtd=True, forbid_entities=True):
            if element.tag in ("record", "transaction"):
                yield {child.tag: [x.text for x in child] if len(child) else child.text
                       for child in element}
                element.clear()
    else:
        raise ValueError("Supported formats: CSV, JSON, JSONL, XML")


def sats(value):
    try:
        amount = Decimal(str(value))
        scaled = amount * 100_000_000
        if not amount.is_finite() or amount < 0 or amount > 21_000_000 or scaled != scaled.to_integral_value():
            raise ValueError("BTC amount must be finite, nonnegative, and have at most 8 decimals")
        return int(scaled)
    except (InvalidOperation, TypeError) as e:
        raise ValueError("Invalid BTC amount") from e


def array(value, name):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as e:
            raise ValueError(f"{name} must be a JSON array") from e
    if not isinstance(value, list) or not value:
        raise ValueError(f"{name} must be a nonempty array")
    return value


def optional_ip(value):
    return str(ipaddress.ip_address(str(value).strip())) if value not in (None, "") else None


def port(value):
    if value in (None, ""):
        return None
    n = int(str(value))
    if not 1 <= n <= 65535:
        raise ValueError("Port outside 1..65535")
    return n


def normalize(raw, mapping=None):
    if not isinstance(raw, dict):
        raise ValueError("Record must be an object")
    if "__parse_error__" in raw:
        raise ValueError(raw["__parse_error__"])
    mapped = {}
    for key, value in raw.items():
        field = (mapping or {}).get(key, ALIASES.get(key, key))
        if field in mapped:
            raise ValueError(f"Ambiguous field mapping for {field}")
        mapped[field] = value
    txid = str(mapped.get("txid", "")).lower().strip()
    if not re.fullmatch(r"[0-9a-f]{64}", txid):
        raise ValueError("txid must contain 64 hexadecimal characters")
    stamp = datetime.fromisoformat(str(mapped.get("timestamp", "")).replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("timestamp needs an explicit timezone")
    out = {"txid": txid, "timestamp": stamp.astimezone(timezone.utc).isoformat()}
    for direction in ("input", "output"):
        addresses = array(mapped.get(direction + "_addresses"), direction + "_addresses")
        amounts = array(mapped.get(direction + "_amounts"), direction + "_amounts")
        if len(addresses) != len(amounts):
            raise ValueError(f"{direction} address/amount array lengths differ")
        if any(not isinstance(a, str) or not a.strip() or len(a) > 200 or any(c.isspace() for c in a) for a in addresses):
            raise ValueError("Address identifiers must be nonempty strings without whitespace (max 200)")
        out[direction + "_addresses"] = addresses
        out[direction + "_sats"] = [sats(a) for a in amounts]
    fee = sum(out["input_sats"]) - sum(out["output_sats"])
    if fee < 0:
        raise ValueError("Outputs exceed inputs; coinbase/partial records require a separate adapter")
    if mapped.get("fee") not in (None, "") and sats(mapped["fee"]) != fee:
        raise ValueError("Reported fee disagrees with input minus output amounts")
    out["fee_sats"] = fee
    vsize = mapped.get('vsize')
    out['vsize'] = int(vsize) if vsize not in (None,'') else None
    if out['vsize'] is not None and not 1 <= out['vsize'] <= 4_000_000:
        raise ValueError('vsize must be a positive integer up to 4,000,000')
    out["script_type"] = str(mapped["script_type"]) if mapped.get("script_type") else None
    for k in ("src_ip", "dst_ip"):
        out[k] = optional_ip(mapped.get(k))
    for k in ("src_port", "dst_port"):
        out[k] = port(mapped.get(k))
    country = mapped.get("geo_country") or None
    if country and not re.fullmatch("[A-Za-z]{2}", str(country)):
        raise ValueError("geo_country must be a two-letter code or blank")
    out["geo_country"] = country.upper() if country else None
    out["asn"] = int(str(mapped["asn"]).removeprefix("AS")) if mapped.get("asn") not in (None, "") else None
    if out["asn"] is not None and not 0 <= out["asn"] <= 4294967295:
        raise ValueError("ASN outside valid range")
    out["geo_source"] = "input_metadata_unverified" if country or out["asn"] is not None else "unavailable"
    return out


class GeoIP:
    """Optional local country and ASN databases; no network lookups."""
    def __init__(self, country=None, asn=None):
        import maxminddb
        self.readers = {name: maxminddb.open_database(str(path)) for name, path in
                        (("country", country), ("asn", asn)) if path}
        self.hashes = {name: file_hash(path) for name, path in (("country", country), ("asn", asn)) if path}

    def enrich(self, record):
        ip = record["src_ip"]
        if not ip:
            return record
        provenance = {"input_metadata": record["geo_source"]}
        for name, reader in self.readers.items():
            result = reader.get(ip) or {}
            value = result.get("country", {}).get("iso_code") if name == "country" else result.get("autonomous_system_number")
            if value is not None:
                record["geo_country" if name == "country" else "asn"] = value
                provenance[name] = {"database_sha256": self.hashes[name], "ip_role": "src_ip"}
        if len(provenance) > 1:
            record["geo_source"] = canonical(provenance)
        return record

    def close(self):
        for reader in self.readers.values():
            reader.close()


def ingest(path, db_path, mapping=None, country_db=None, asn_db=None, tor_snapshot=None, max_gap_seconds=None):
    path, db_path = Path(path).resolve(), Path(db_path)
    source_hash = file_hash(path)
    db = connect(db_path)
    if db.execute("SELECT 1 FROM sources WHERE hash=?", (source_hash,)).fetchone():
        db.close()
        return {"already_ingested": True, "source_sha256": source_hash}
    archive = db_path.parent / "evidence" / (source_hash + path.suffix.lower())
    archive.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(path, archive)
    if file_hash(archive) != source_hash:
        raise ValueError("Source changed during evidence capture; retry with a stable file")
    geo = GeoIP(country_db, asn_db)
    tor = json.loads(Path(tor_snapshot).read_text()) if tor_snapshot else None
    if tor:
        tor['ips'] = set(tor['ips'])
        tor_start = datetime.fromisoformat(tor['valid_from'].replace('Z','+00:00'))
        tor_end = datetime.fromisoformat(tor['valid_until'].replace('Z','+00:00'))
        if tor_start.tzinfo is None or tor_end.tzinfo is None or tor_start >= tor_end:
            raise ValueError('Tor snapshot requires a valid timezone-aware interval')
    unmapped, gap_warnings = set(), []
    previous_time = None
    counts = {"accepted": 0, "quarantined": 0, "duplicates": 0, "new_transactions": 0}
    try:
        with db:
            db.execute("INSERT INTO sources VALUES (?,?,?,?)", (source_hash, path.name, str(archive.resolve()), path.suffix.lower()))
            audit(db, {"event": "source_ingested", "sha256": source_hash, "name": path.name,
                       "mapping": mapping or {}, "geo_databases": geo.hashes})
            seen = 0
            for index, raw in enumerate(records(archive), 1):
                seen += 1
                raw_hash = digest(raw)
                try:
                    r = geo.enrich(normalize(raw, mapping))
                    unmapped.update(k for k in raw if (mapping or {}).get(k,ALIASES.get(k,k)) not in KNOWN_FIELDS)
                    stamp = datetime.fromisoformat(r['timestamp'])
                    if previous_time is not None and abs((stamp-previous_time).total_seconds()) > (max_gap_seconds or 86400):
                        gap = abs((stamp-previous_time).total_seconds())
                        if len(gap_warnings)<100: gap_warnings.append({'row':index,'gap_seconds':gap})
                        if max_gap_seconds: raise ValueError('Timestamp gap exceeds operator-configured maximum')
                    previous_time = stamp
                    r['tor_exit'] = (r['src_ip'] in tor['ips']) if tor and tor_start <= stamp <= tor_end and r['src_ip'] else None
                    r['tor_snapshot_sha256'] = file_hash(tor_snapshot) if tor else None
                    chain = {k: r[k] for k in ("txid", "input_addresses", "output_addresses", "input_sats", "output_sats", "fee_sats", "script_type", "vsize")}
                    previous = db.execute("SELECT chain_json FROM transactions WHERE txid=?", (r["txid"],)).fetchone()
                    if previous and previous[0] != canonical(chain):
                        raise ValueError("Conflicting blockchain fields for an existing TXID")
                    obs_id = digest({k: r[k] for k in ("txid", "timestamp", "src_ip", "dst_ip", "src_port", "dst_port")})
                    if not previous:
                        db.execute("INSERT INTO transactions VALUES (?,?,?,?,?)", (r["txid"], canonical(chain), r["timestamp"], r["fee_sats"], r["script_type"]))
                        for direction in ("input", "output"):
                            db.executemany("INSERT INTO flows VALUES (?,?,?,?,?)", [(r["txid"], direction, i, a, v) for i, (a, v) in enumerate(zip(r[direction + "_addresses"], r[direction + "_sats"]))])
                        counts["new_transactions"] += 1
                    else:
                        db.execute("UPDATE transactions SET first_seen=MIN(first_seen,?) WHERE txid=?", (r["timestamp"], r["txid"]))
                    if db.execute("SELECT 1 FROM observations WHERE id=?", (obs_id,)).fetchone():
                        counts["duplicates"] += 1
                        status = "duplicate"
                    else:
                        db.execute("INSERT INTO observations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (obs_id, r["txid"], r["timestamp"], r["src_ip"], r["dst_ip"], r["src_port"], r["dst_port"], r["geo_country"], r["asn"], r["geo_source"], source_hash, index, canonical(r)))
                        counts["accepted"] += 1
                        status = "accepted"
                    audit(db, {"event": status, "source": source_hash, "row": index, "raw_sha256": raw_hash, "observation_id": obs_id, "normalized_sha256": digest(r)})
                except (ValueError, TypeError, KeyError, OverflowError) as e:
                    counts["quarantined"] += 1
                    db.execute("INSERT INTO quarantine(source_hash,source_row,error,raw_json) VALUES (?,?,?,?)", (source_hash, index, str(e), canonical(raw)))
                    audit(db, {"event": "quarantined", "source": source_hash, "row": index, "raw_sha256": raw_hash, "error": str(e)})
            if not seen:
                raise ValueError("No records found; expected JSON array / records array, or XML record/transaction elements")
            set_meta(db, "last_ingest", counts)
            schema_report = {'unmapped_fields':sorted(unmapped),'timestamp_gap_warnings':gap_warnings,
                             'source_sha256':source_hash,'review_required':bool(unmapped or gap_warnings)}
            set_meta(db,'schema_report',schema_report)
            audit(db,{'event':'schema_review',**schema_report})
            # Existing alerts are stale after any new input; require explicit scoring.
            db.execute("DELETE FROM alerts")
            set_meta(db, "scored", False)
        return {**counts, "source_sha256": source_hash}
    finally:
        geo.close()
        db.close()
