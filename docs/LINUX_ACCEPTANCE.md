# Linux execution evidence

## User-reported Kali run

The operator supplied the following terminal output from Kali Linux. This is
user-reported evidence; the maintainer did not directly execute or inspect this
host. The execution date, commit and complete environment were not supplied.

Working directory: `~/Downloads/parallax-codex-dashboard-demo-handoff`.
Case directory: `data/recovered-demo`.

```text
benchmark.json      case.sqlite      evidence  keys   sample-case.zip        train.sqlite
calibration.sqlite  evaluation.json  fixtures  model  signer-public-key.txt

$ parallax serve --data data/recovered-demo --port 8765
INFO:     Started server process [55690]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8765 (Press CTRL+C to quit)
```

This supports successful native Linux server startup and the presence of demo
artifacts. It does not by itself establish passing tests, valid signatures,
browser rendering, model metrics, GeoIP enrichment or network-isolated execution.
The benchmark and evaluation contents have not yet been provided from this host.

## Complete the acceptance capture

Leave the server running. In a second Kali terminal, run from the repository root:

```bash
source .venv/bin/activate
mkdir -p acceptance/linux
date -u > acceptance/linux/environment.txt
uname -a >> acceptance/linux/environment.txt
python --version >> acceptance/linux/environment.txt
python -m pip freeze > acceptance/linux/packages.txt
# A downloaded ZIP may have no Git metadata; record that if this fails.
git rev-parse HEAD > acceptance/linux/commit.txt 2> acceptance/linux/commit-error.txt
python -m pytest -q > acceptance/linux/tests.txt 2>&1
echo "pytest exit: $?"
parallax verify-audit --db data/recovered-demo/case.sqlite > acceptance/linux/audit.json
echo "audit exit: $?"
parallax verify-case data/recovered-demo/sample-case.zip --trusted-key data/recovered-demo/signer-public-key.txt > acceptance/linux/dossier.json
echo "dossier exit: $?"
curl --fail --silent --show-error http://127.0.0.1:8765/ -o acceptance/linux/dashboard.html
echo "HTTP exit: $?"
cp data/recovered-demo/benchmark.json data/recovered-demo/evaluation.json acceptance/linux/
```

Every displayed exit code must be zero; preserve failures rather than describing
them as passes. The bundled public key checks internal consistency; independent
provenance requires a separately trusted key and audit anchor.

Open `http://127.0.0.1:8765` in the Kali browser and capture screenshots of
Investigative leads (including a selected lead and graph), Model validation,
and Evidence & sources. Store them under `acceptance/linux/`. Review the files
before sharing, as environment logs may contain host identifiers. Do not include
`data/recovered-demo/keys/`, which contains private signing material.

Network isolation remains a separate check; a successful native startup does
not establish the Docker `--network none` test result.
