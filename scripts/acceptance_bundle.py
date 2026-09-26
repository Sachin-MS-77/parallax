#!/usr/bin/env python3
"""Create a reviewable offline acceptance bundle for a scored PARALLAX case."""
import argparse
import json
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path


def command(*args):
    binary = shutil.which("parallax")
    return [binary, *args] if binary else [sys.executable, "-m", "parallax.cli", *args]


def run(label, args, destination):
    result = subprocess.run(args, capture_output=True, text=True)
    (destination / f"{label}.stdout").write_text(result.stdout)
    (destination / f"{label}.stderr").write_text(result.stderr)
    return {"label": label, "command": args, "exit_code": result.returncode}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, help="Scored demo/case directory")
    parser.add_argument("--out", default="acceptance/latest", help="Acceptance output directory")
    parser.add_argument("--skip-tests", action="store_true")
    args = parser.parse_args()
    data, out = Path(args.data).resolve(), Path(args.out).resolve()
    if not (data / "case.sqlite").is_file():
        raise SystemExit(f"Missing {data / 'case.sqlite'}; run parallax demo or ingest/train/score first")
    out.mkdir(parents=True, exist_ok=True)
    checks = []
    if not args.skip_tests:
        checks.append(run("tests", [sys.executable, "-m", "pytest", "-q"], out))
    checks.append(run("audit", command("verify-audit", "--db", str(data / "case.sqlite")), out))
    checks.append(run("dossier", command("verify-case", str(data / "sample-case.zip"), "--trusted-key", str(data / "signer-public-key.txt")), out))
    if (data / "benchmark.json").is_file(): shutil.copy2(data / "benchmark.json", out / "benchmark.json")
    if (data / "evaluation.json").is_file(): shutil.copy2(data / "evaluation.json", out / "evaluation.json")
    run("audit-export", command("export-audit", "--db", str(data / "case.sqlite"), "--out", str(out / "original-audit.jsonl")), out)
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = "unavailable"
    manifest = {"created_at": datetime.now(timezone.utc).isoformat(), "data": str(data), "commit": commit, "checks": checks,
                "scope": "Offline acceptance evidence; synthetic or supplied metadata only"}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    archive = out.parent / f"{out.name}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in out.iterdir():
            if path.is_file() and path.name != archive.name:
                bundle.write(path, path.name)
    print(json.dumps({"directory": str(out), "archive": str(archive), "checks": checks}, indent=2))
    raise SystemExit(0 if all(c["exit_code"] == 0 for c in checks) else 1)


if __name__ == "__main__":
    main()
