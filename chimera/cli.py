import argparse
import json
import platform
import resource
import sys
import time
import zipfile
from pathlib import Path

from .evidence import dossier, keypair, verify_dossier, verify_pdf
from .evaluate import evaluate
from .ingest import ingest
from .model import score, train
from .storage import connect, file_hash, set_meta, verify_state
from .synthetic import generate


def demo(root, entities=160):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    if any((root / name).exists() for name in ("case.sqlite", "train.sqlite", "calibration.sqlite", "model")):
        raise ValueError("Demo output already exists; use another --data directory to preserve prior evidence")
    started = time.perf_counter()
    generated = {}
    for split, size in (("train", max(200, entities)), ("calibration", entities), ("test", entities)):
        generated[split] = generate(root / "fixtures", split, size)
        path = root / ("case.sqlite" if split == "test" else split + ".sqlite")
        ingest(root / "fixtures" / (split + ".jsonl"), path)
        db = connect(path)
        with db:
            set_meta(db, "domain", "synthetic")
            set_meta(db, "split", split)
        db.close()
    train(root / "train.sqlite", root / "model", root / "calibration.sqlite", root / "fixtures/calibration-labels.json", graph_labels=root/'fixtures/train-labels.json')
    scoring = score(root / "case.sqlite", root / "model")
    report = evaluate(root / "case.sqlite", root / "model", root / "fixtures/test-labels.json", root / "evaluation.json")
    db = connect(root / "case.sqlite")
    first = db.execute("SELECT address FROM alerts ORDER BY priority DESC,address LIMIT 1").fetchone()[0]
    (root / "sample-case.zip").write_bytes(dossier(db, first, root / "keys"))
    _, public = keypair(root / "keys")
    (root / "signer-public-key.txt").write_text(public.hex())
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    benchmark = {"elapsed_seconds": round(time.perf_counter() - started, 3),
                 "peak_rss_mb": round(peak / (1024 * 1024 if sys.platform == "darwin" else 1024), 2),
                 "platform": platform.platform(), "python": platform.python_version(),
                 "generated": generated, "scope": "Full demo: generation, ingest, training, scoring, evaluation, dossier export"}
    with db:
        set_meta(db, "benchmark", benchmark)
    db.close()
    (root / "benchmark.json").write_text(json.dumps(benchmark, indent=2))
    return {"data": str(root), "scoring": scoring, "baselines": report["baselines"], "benchmark": benchmark}


def parser():
    p = argparse.ArgumentParser(prog="chimera", description="Offline Bitcoin metadata investigation workbench")
    sub = p.add_subparsers(dest="command", required=True)
    d = sub.add_parser("demo", help="Build reproducible synthetic demo and train real models")
    d.add_argument("--data", default="data/demo")
    d.add_argument("--entities", type=int, default=160)
    g = sub.add_parser("generate", help="Generate metadata fixtures and separate labels")
    g.add_argument("--out", required=True)
    g.add_argument("--split", choices=("train", "calibration", "test"), default="test")
    g.add_argument("--entities", type=int, default=160)
    i = sub.add_parser("ingest", help="Validate and ingest CSV/JSON/JSONL/XML")
    i.add_argument("file")
    i.add_argument("--db", required=True)
    i.add_argument("--mapping", help="JSON object mapping source headers to canonical fields")
    i.add_argument("--country-db")
    i.add_argument("--asn-db")
    i.add_argument('--tor-snapshot')
    i.add_argument('--max-gap-seconds',type=float)
    t = sub.add_parser("train", help="Train from representative reference data")
    t.add_argument("--db", required=True)
    t.add_argument("--out", required=True)
    t.add_argument("--calibration-db")
    t.add_argument("--labels")
    t.add_argument('--graph-labels')
    s = sub.add_parser("score")
    s.add_argument("--db", required=True)
    s.add_argument("--model", required=True)
    e = sub.add_parser("evaluate")
    e.add_argument("--db", required=True)
    e.add_argument("--model", required=True)
    e.add_argument("--labels", required=True)
    e.add_argument("--out", required=True)
    v = sub.add_parser("verify-audit")
    v.add_argument("--db", required=True)
    v.add_argument("--expected-head")
    c = sub.add_parser("export")
    c.add_argument("--db", required=True)
    c.add_argument("--address", required=True)
    c.add_argument("--out", required=True)
    c = sub.add_parser("verify-case")
    c.add_argument("file")
    c.add_argument("--trusted-key", help="File containing separately retained signer public key")
    c = sub.add_parser('export-pdf',help='Export a signed PDF and its detached signature from a scored alert')
    c.add_argument('--db',required=True); c.add_argument('--address',required=True); c.add_argument('--pdf',required=True); c.add_argument('--signature',required=True); c.add_argument('--public-key',required=True)
    w = sub.add_parser("serve")
    w.add_argument("--data", default="data/demo")
    w.add_argument("--port", type=int, default=8765)
    inspect=sub.add_parser('inspect',help='Inspect source format before importing')
    inspect.add_argument('file')
    seed=sub.add_parser('seeds',help='Set independently sourced seed addresses')
    seed.add_argument('--db',required=True); seed.add_argument('--file',required=True)
    fb=sub.add_parser('feedback',help='Train a new ensemble version from explicit analyst 0/1 labels')
    fb.add_argument('--db',required=True); fb.add_argument('--model',required=True)
    fb.add_argument('--labels',required=True); fb.add_argument('--out',required=True)
    for name in ('stress-test','case-replay'):
        v=sub.add_parser(name); v.add_argument('--model',required=True); v.add_argument('--out',required=True)
    pdf=sub.add_parser('verify-pdf'); pdf.add_argument('file'); pdf.add_argument('--signature',required=True); pdf.add_argument('--trusted-key',required=True)
    return p


def main():
    args = parser().parse_args()
    try:
        if args.command == "demo":
            if args.entities < 40:
                raise ValueError("Demo requires at least 40 entities per evaluation split")
            result = demo(args.data, args.entities)
        elif args.command == "generate":
            if args.entities < 1:
                raise ValueError("entities must be positive")
            result = generate(args.out, args.split, args.entities)
        elif args.command == "ingest":
            mapping = json.loads(Path(args.mapping).read_text()) if args.mapping else None
            result = ingest(args.file, args.db, mapping, args.country_db, args.asn_db,args.tor_snapshot,args.max_gap_seconds)
            db = connect(args.db)
            with db:
                set_meta(db, "domain", "unknown")
                set_meta(db, "evaluation", None)
            db.close()
        elif args.command == "train":
            result = train(args.db, args.out, args.calibration_db, args.labels,graph_labels=args.graph_labels)
        elif args.command == "score":
            result = score(args.db, args.model)
        elif args.command == "evaluate":
            result = evaluate(args.db, args.model, args.labels, args.out)
        elif args.command == "verify-audit":
            db = connect(args.db)
            result = verify_state(db, args.expected_head)
            result["sources_intact"] = all(Path(r["stored_path"]).exists() and file_hash(r["stored_path"]) == r["hash"] for r in db.execute("SELECT * FROM sources"))
            db.close()
            if not result["valid"] or not result["sources_intact"]:
                print(json.dumps(result, indent=2))
                raise SystemExit(1)
        elif args.command == "export":
            db = connect(args.db)
            Path(args.out).write_bytes(dossier(db, args.address, Path(args.db).parent / "keys"))
            db.close()
            result = {"exported": args.out}
        elif args.command == "verify-case":
            result = verify_dossier(args.file, Path(args.trusted_key).read_text() if args.trusted_key else None)
        elif args.command=='export-pdf':
            db=connect(args.db)
            archive=dossier(db,args.address,Path(args.db).parent/'keys'); db.close()
            with zipfile.ZipFile(__import__('io').BytesIO(archive)) as z:
                for name,target in (('report.pdf',args.pdf),('report.pdf.sig',args.signature),('public-key.txt',args.public_key)):
                    Path(target).write_bytes(z.read(name))
            result={'pdf':args.pdf,'signature':args.signature,'public_key':args.public_key}
        elif args.command == "serve":
            import uvicorn
            from .server import create_app
            uvicorn.run(create_app(Path(args.data).resolve()), host="127.0.0.1", port=args.port, access_log=False)
            return
        elif args.command=='inspect':
            from .ingest import records
            path=Path(args.file)
            with path.open('rb') as stream: magic=stream.read(8)
            if magic.startswith(b'%PDF'):
                raise ValueError('This file is a PDF document, not CSV/JSON/XML transaction metadata')
            iterator=records(path); sample=next(iterator,None)
            result={'sha256':file_hash(path),'bytes':path.stat().st_size,'sample_fields':sorted(sample) if isinstance(sample,dict) else [],'sample':sample}
        elif args.command=='seeds':
            seeds=json.loads(Path(args.file).read_text())
            if not isinstance(seeds,list) or any(not s.get('address') or not s.get('source') for s in seeds):
                raise ValueError('Seeds require a JSON list of address/source objects')
            from .storage import audit
            db=connect(args.db)
            with db:
                set_meta(db,'seed_addresses',seeds); set_meta(db,'scored',False); db.execute('DELETE FROM alerts')
                audit(db,{'event':'seed_update','sha256':file_hash(args.file),'count':len(seeds)})
            db.close(); result={'seeds':len(seeds),'rescore_required':True}
        elif args.command=='feedback':
            from .feedback import feedback_update
            result=feedback_update(args.db,args.model,args.labels,args.out)
        elif args.command=='stress-test':
            from .validation import adaptive
            result=adaptive(args.model,args.out)
        elif args.command=='case-replay':
            from .validation import case_replay
            result=case_replay(args.model,args.out)
        elif args.command=='verify-pdf':
            result=verify_pdf(args.file,args.signature,args.trusted_key)
        print(json.dumps(result, indent=2))
    except (ValueError, FileNotFoundError, KeyError) as e:
        print(f"CHIMERA: {e}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
