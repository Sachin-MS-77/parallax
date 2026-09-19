"""Local-only dashboard API; no remote services, fonts, telemetry, or model downloads."""
import csv
import io
import json
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .evidence import dossier, get_alert
from .graph import graph
from .ingest import ingest
from .model import score
from .storage import audit, connect, file_hash, get_meta, set_meta, verify_audit, verify_state


class Review(BaseModel):
    address: str = Field(min_length=1, max_length=200)
    status: str
    reason: str = Field(min_length=5, max_length=2000)


def create_app(data):
    data = Path(data)
    db_path, model_dir = data / "case.sqlite", data / "model"
    if not db_path.exists() or not (model_dir / "manifest.json").exists():
        raise ValueError("Missing case.sqlite or model/manifest.json. Run parallax demo or ingest/train/score first.")
    app = FastAPI(title="CHIMERA offline workbench", docs_url=None, redoc_url=None)
    lock = threading.Lock()

    @app.middleware("http")
    async def local_only(request, call_next):
        host = request.url.hostname
        if host not in ("127.0.0.1", "localhost", "testserver", "::1"):
            return JSONResponse({"detail": "Only localhost access is allowed"}, 403)
        origin = request.headers.get("origin")
        if origin and origin != f"{request.url.scheme}://{request.url.netloc}":
            return JSONResponse({"detail": "Cross-origin access is disabled"}, 403)
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/summary")
    def summary():
        db = connect(db_path)
        try:
            counts = {name: db.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] for name in
                      ("transactions", "observations", "alerts", "quarantine", "sources")}
            counts["addresses"] = db.execute("SELECT COUNT(DISTINCT address) FROM flows").fetchone()[0]
            threshold=(get_meta(db,'model') or {}).get('priority_threshold',80)
            counts["high_priority"] = db.execute("SELECT COUNT(*) FROM alerts WHERE priority>=?",(threshold,)).fetchone()[0]
            counts["review_priority"] = db.execute("SELECT COUNT(*) FROM alerts WHERE priority>=? AND priority<?",(.75*threshold,threshold)).fetchone()[0]
            counts["low_priority"] = counts["alerts"]-counts["high_priority"]-counts["review_priority"]
            counts["total_btc"] = db.execute("SELECT COALESCE(SUM(amount_sats),0)/100000000.0 FROM flows WHERE direction='output'").fetchone()[0]
            counts["reviewed"] = db.execute("SELECT COUNT(DISTINCT address) FROM reviews").fetchone()[0]
            return {"counts": counts, "domain": get_meta(db, "domain", "unknown"), "model": get_meta(db, "model"),
                    "evaluation": get_meta(db, "evaluation"), "benchmark": get_meta(db, "benchmark"),
                    "drift":get_meta(db,'drift'),
                    "scored": get_meta(db, "scored", False), "scored_at": get_meta(db, "scored_at"),
                    "timeline": [dict(r) for r in db.execute("SELECT SUBSTR(first_seen,1,13) AS hour,COUNT(*) AS transactions FROM transactions GROUP BY hour ORDER BY hour")],
                    "integrity": verify_audit(db)}
        finally:
            db.close()

    @app.get("/api/alerts")
    def alerts(q: str = "", band: str = "all", status: str = "all", offset: int = 0, limit: int = 40):
        db = connect(db_path)
        try:
            threshold=(get_meta(db,'model') or {}).get('priority_threshold',80)
            low, high = {"all": (0, 101), "high": (threshold, 101), "review": (.75*threshold,threshold), "low": (0,.75*threshold)}.get(band, (0, 101))
            params = [low, high, q, status, status]
            clause = """FROM alerts a WHERE priority>=? AND priority<? AND instr(a.address,?)>0
                AND (?='all' OR COALESCE((SELECT r.status FROM reviews r WHERE r.address=a.address ORDER BY r.id DESC LIMIT 1),'New')=?)"""
            total = db.execute("SELECT COUNT(*) " + clause, params).fetchone()[0]
            rows = []
            for r in db.execute("SELECT address " + clause + " ORDER BY priority DESC,address LIMIT ? OFFSET ?", params + [max(1, min(limit, 100)), max(0, offset)]):
                a = get_alert(db, r["address"])
                rows.append({k: a[k] for k in ("address", "priority", "priority_band", "tx_count", "total_btc", "evidence_quality", "behavior_group", "status", "rules", "model_percentile")})
            return {"items": rows, "total": total, "offset": offset}
        finally:
            db.close()

    @app.get("/api/alert")
    def alert(address: str):
        db = connect(db_path)
        try:
            return get_alert(db, address)
        except KeyError:
            raise HTTPException(404, "Profile not found")
        finally:
            db.close()

    @app.get("/api/graph")
    def graph_data(address: str, layer: str = "fused"):
        db = connect(db_path)
        try:
            return graph(db, address, layer, limit=6)
        except ValueError as e:
            raise HTTPException(400, str(e))
        finally:
            db.close()

    @app.get("/api/sources")
    def sources():
        db = connect(db_path)
        try:
            return {"sources": [dict(r) for r in db.execute("SELECT hash,name,format FROM sources")],
                    "schema_report":get_meta(db,'schema_report',{}),
                    "quarantine_count": db.execute("SELECT COUNT(*) FROM quarantine").fetchone()[0],
                    "quarantine": [dict(r) for r in db.execute("SELECT source_hash,source_row,error FROM quarantine ORDER BY id LIMIT 100")],
                    "audit": [dict(r) for r in db.execute("SELECT * FROM audit ORDER BY seq DESC LIMIT 30")]}
        finally:
            db.close()

    @app.get("/api/integrity")
    def integrity():
        db = connect(db_path)
        try:
            result = verify_state(db)
            result["sources"] = [{"name": r["name"], "valid": Path(r["stored_path"]).is_file() and file_hash(r["stored_path"]) == r["hash"]} for r in db.execute("SELECT * FROM sources")]
            return result
        finally:
            db.close()

    @app.post("/api/review")
    def review(body: Review):
        if body.status not in ("New", "Triaging", "Escalated", "Dismissed") or len(body.reason.strip()) < 5:
            raise HTTPException(400, "Choose a valid state and give a meaningful review reason")
        with lock:
            db = connect(db_path)
            try:
                get_alert(db, body.address)
                stamp = datetime.now(timezone.utc).isoformat()
                with db:
                    db.execute("INSERT INTO reviews(address,status,reason,timestamp) VALUES (?,?,?,?)", (body.address, body.status, body.reason.strip(), stamp))
                    audit(db, {"event": "analyst_review", **body.model_dump(), "timestamp": stamp})
                return {"saved": True, "status": body.status}
            except KeyError:
                raise HTTPException(404, "Profile not found")
            finally:
                db.close()

    @app.get("/api/export")
    def export(address: str):
        with lock:
            db = connect(db_path)
            try:
                result = dossier(db, address, data / "keys")
                return Response(result, media_type="application/zip", headers={"Content-Disposition": 'attachment; filename="parallax-case.zip"'})
            except KeyError:
                raise HTTPException(404, "Profile not found")
            except ValueError as e:
                raise HTTPException(409, str(e))
            finally:
                db.close()

    @app.get("/api/export-alerts")
    def export_alerts():
        db = connect(db_path)
        try:
            out = io.StringIO()
            fields = ["address", "priority", "priority_band", "evidence_quality", "status", "tx_count", "total_btc", "behavior_group"]
            writer = csv.DictWriter(out, fields)
            writer.writeheader()
            for row in db.execute("SELECT address FROM alerts ORDER BY priority DESC,address"):
                a = get_alert(db, row[0])
                # Prevent spreadsheet formula execution when exporting imported identifiers.
                writer.writerow({k: "'" + a[k] if isinstance(a[k], str) and a[k].startswith(("=", "+", "-", "@", "\t", "\r")) else a[k] for k in fields})
            return Response(out.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="parallax-alerts.csv"'})
        finally:
            db.close()

    @app.post("/api/import")
    async def import_file(request: Request):
        name = Path(request.headers.get("x-filename", "upload.jsonl")).name
        extension = Path(name).suffix.lower()
        if extension not in (".csv", ".json", ".jsonl", ".ndjson", ".xml"):
            raise HTTPException(400, "Choose CSV, JSON, JSONL, or XML metadata")
        upload_dir = data / "imports"
        upload_dir.mkdir(exist_ok=True)
        with tempfile.NamedTemporaryFile(suffix=extension, dir=upload_dir, delete=False) as f:
            path = Path(f.name)
            size = 0
            try:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > 25 * 1024 * 1024:
                        raise HTTPException(413, "Dashboard upload limit is 25 MB; use the CLI for bulk files")
                    f.write(chunk)
            except Exception:
                path.unlink(missing_ok=True)
                raise
        def process():
            with lock:
                result = ingest(path, db_path)
                db = connect(db_path)
                with db:
                    set_meta(db, "domain", "unknown")
                    set_meta(db, "evaluation", None)
                    audit(db, {"event": "dashboard_import", "filename": name, "source_sha256": result["source_sha256"]})
                db.close()
                return {"ingest": result, "scoring": score(db_path, model_dir)}
        try:
            return await run_in_threadpool(process)
        except Exception as e:
            raise HTTPException(400, f"Import failed: {e}")
        finally:
            path.unlink(missing_ok=True)

    static = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static), name="static")

    @app.get("/")
    def index():
        return FileResponse(static / "index.html")

    return app
