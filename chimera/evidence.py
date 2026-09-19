"""Signed portable case dossiers; integrity does not imply attribution or admissibility."""
import base64
import hashlib
import html
import io
import json
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .graph import graph
from .pdfreport import report_pdf
from .storage import audit, canonical, file_hash, get_meta, verify_state


def keypair(directory):
    path = Path(directory) / "signing.key"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        key = Ed25519PrivateKey.generate()
        raw = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
    key = Ed25519PrivateKey.from_private_bytes(path.read_bytes())
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return key, public


def get_alert(db, address):
    row = db.execute("SELECT payload FROM alerts WHERE address=?", (address,)).fetchone()
    if not row:
        raise KeyError("Address has no scored profile")
    alert = json.loads(row[0])
    alert["reviews"] = [dict(r) for r in db.execute("SELECT status,reason,timestamp FROM reviews WHERE address=? ORDER BY id", (address,))]
    if alert["reviews"]:
        alert["status"] = alert["reviews"][-1]["status"]
    return alert


def dossier(db, address, key_dir):
    alert = get_alert(db, address)
    integrity = verify_state(db)
    if not integrity["valid"]:
        raise ValueError("Audit trail failed verification; export refused")
    sources = [dict(r) for r in db.execute("SELECT * FROM sources ORDER BY hash")]
    for source in sources:
        if not Path(source["stored_path"]).is_file() or file_hash(source["stored_path"]) != source["hash"]:
            raise ValueError("Archived source failed integrity verification")
        source.pop("stored_path")
    observations = [dict(r) for r in db.execute("""SELECT o.* FROM observations o JOIN
       (SELECT DISTINCT txid FROM flows WHERE address=?) f ON f.txid=o.txid ORDER BY o.timestamp""", (address,))]
    payload = {"format": "chimera-case-v1", "exported_at": datetime.now(timezone.utc).isoformat(),
               "scope": "Investigative lead only; no ownership attribution or legal certification",
               "alert": alert, "graph": graph(db, address, limit=30), "observations": observations,
               "sources": sources, "model": get_meta(db, "model"), "audit_anchor": integrity}
    case_bytes = canonical(payload).encode()
    # Print-friendly offline HTML is covered by the signed manifest too.
    escape = html.escape
    report = f"""<!doctype html><html><head><meta charset="utf-8"><title>CHIMERA case dossier</title>
<style>body{{font:15px system-ui;max-width:900px;margin:40px auto;color:#182c3c}}h1{{letter-spacing:3px}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#f1f5f7;padding:20px}}@media print{{body{{margin:0}}}}</style></head>
<body><h1>CHIMERA / CASE DOSSIER</h1><p>{escape(payload['scope'])}</p>
<h2>{escape(address)}</h2><p>Priority: {alert['priority']}/100 · Evidence quality: {alert['evidence_quality']}/100</p>
<p>Neither value is the probability of criminal activity. Model: {escape(alert['model_sha256'])}</p>
<h3>Reasons and limitations</h3><pre>{escape(json.dumps({'rules':alert['rules'],'sensitivity':alert['explanations'],'caveats':alert['caveats']},indent=2))}</pre>
<h3>Source references</h3><pre>{escape(json.dumps(alert['evidence'],indent=2))}</pre>
<p>The companion case.json contains the complete exported evidence. Verify the signed manifest with a separately trusted public key.</p></body></html>""".encode()
    pdf = report_pdf(payload)
    key, public = keypair(key_dir)
    files = {"case.json": case_bytes, "report.html": report, "report.pdf":pdf,
             "report.pdf.sig":base64.b64encode(key.sign(pdf))}
    manifest = {"format": "chimera-signature-v1", "algorithm": "Ed25519",
                "files": {name: hashlib.sha256(body).hexdigest() for name, body in files.items()}}
    manifest_bytes = canonical(manifest).encode()
    key, public = keypair(key_dir)
    signature = key.sign(manifest_bytes)
    files.update({"manifest.json": manifest_bytes, "signature.txt": base64.b64encode(signature),
                  "public-key.txt": public.hex().encode()})
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        for name, body in files.items():
            z.writestr(name, body)
    with db:
        audit(db, {"event": "case_exported", "address": address, "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                   "signer_fingerprint": hashlib.sha256(public).hexdigest()})
    return buffer.getvalue()


def verify_dossier(path, trusted_public_key=None):
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Duplicate archive entries")
        public = bytes.fromhex(z.read("public-key.txt").decode())
        if trusted_public_key is not None and public.hex() != trusted_public_key.strip():
            raise ValueError("Signer does not match the separately trusted key")
        body = z.read("manifest.json")
        Ed25519PublicKey.from_public_bytes(public).verify(base64.b64decode(z.read("signature.txt")), body)
        manifest = json.loads(body)
        expected_files = {'case.json','report.html','report.pdf','report.pdf.sig'} if 'report.pdf' in manifest['files'] else {'case.json','report.html'}
        if set(manifest["files"]) != expected_files or set(names) != expected_files | {"manifest.json", "signature.txt", "public-key.txt"}:
            raise ValueError("Unexpected dossier contents")
        for name, expected in manifest["files"].items():
            if hashlib.sha256(z.read(name)).hexdigest() != expected:
                raise ValueError(f"Content hash mismatch: {name}")
        if 'report.pdf' in names:
            Ed25519PublicKey.from_public_bytes(public).verify(base64.b64decode(z.read('report.pdf.sig')),z.read('report.pdf'))
    return {"valid": True, "signer_fingerprint": hashlib.sha256(public).hexdigest(),
            "signer_trusted": trusted_public_key is not None,
            "note": "Without a separately trusted key, verification proves internal consistency only"}


def verify_pdf(path, signature, public_key):
    public=bytes.fromhex(Path(public_key).read_text().strip())
    Ed25519PublicKey.from_public_bytes(public).verify(base64.b64decode(Path(signature).read_bytes()),Path(path).read_bytes())
    return {'valid':True,'algorithm':'Ed25519 detached signature','pdf_sha256':file_hash(path)}
