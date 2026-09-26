# Mac development and Linux teammate handoff

Use Python 3.12 for the Linux handoff; the latest local verification used Python 3.14 on macOS. Python 3.11+ is declared supported. No Linux VM is needed to develop or record the Mac demo.

## On either Mac or Ubuntu/Linux

Open a terminal in the cloned PARALLAX repository:

```bash
bash scripts/install.sh
source .venv/bin/activate
python -m pytest -q
parallax demo --data data/video-demo --entities 160
parallax serve --data data/video-demo --port 8877
```

The installer reuses only the repository's `.venv`, disables pip's download
cache, checks Linux disk space before downloading CPU PyTorch, and prints a
recovery command when an install is interrupted. On Kali/Debian, install the
system prerequisites once if needed:

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip
```

Use Python 3.12 on Linux when available. Before installing, make sure at least
2 GB is free because the CPU PyTorch wheel and temporary build files are large:

```bash
df -h .
PIP_NO_CACHE_DIR=1 bash scripts/install.sh
source .venv/bin/activate
```

If a previous attempt was interrupted, do not use a stale shell command from a
deleted environment. Start a new terminal or run `deactivate`, then rerun the
installer from the repository root. If the preflight reports a full disk, use
`du -xhd1 ~ | sort -h` to find large directories and
`python3 -m pip cache purge` to remove cached downloads.

### Kali troubleshooting

PARALLAX does not use the Elastic APT repository. If `apt-get update` reports a
SHA-1 signing-binding error for `artifacts.elastic.co`, temporarily disable that
third-party source under `/etc/apt/sources.list.d/` and update Kali again. For
the common Kali `.sources` filename, the reversible command is:

```bash
sudo mv /etc/apt/sources.list.d/elastic.sources \
  /etc/apt/sources.list.d/elastic.sources.disabled
```

Do not disable the Kali source. Then install the venv package matching the
Python interpreter shown by the installer; for Python 3.13:

```bash
sudo apt-get update
sudo apt-get install --no-upgrade -y python3.13-venv python3-pip
```

If the failed run left a partial environment, move that project-local directory
aside and let the installer create a clean one:

```bash
if [ -d .venv ]; then mv .venv .venv.failed; fi
PIP_NO_CACHE_DIR=1 bash scripts/install.sh
source .venv/bin/activate
```

Restore the optional Elastic source later with:

```bash
sudo mv /etc/apt/sources.list.d/elastic.sources.disabled \
  /etc/apt/sources.list.d/elastic.sources
```

The Elastic signature warning and a missing Python venv package are separate
host configuration issues; neither indicates a PARALLAX parsing or model error.

Open **http://127.0.0.1:8877**. The demo command creates training, calibration and held-out synthetic test splits, trains models and attaches evaluation. It refuses to overwrite an existing demo directory: choose a new directory when repeating. Keep the terminal running; press Ctrl+C to stop.

The dashboard's **Import metadata** action first opens an intake gate. Review
the detected fields, source size and SHA-256 preview, then choose **Confirm and
ingest**. Selecting a lead exposes the evidence lift from the chain-only model
to the fused model. The graph timeline slider filters transactions by recorded
UTC time; clicking an edge shows its source row and provenance when available.

After a scored run, produce a handoff bundle with:

```bash
./scripts/acceptance_bundle.py --data data/video-demo --out acceptance/video-demo
```

For the simplest connected Kali/Linux path, use the wrapper. It installs into
`.venv`, runs the tests, creates a fresh synthetic case, and starts the server:

```bash
bash scripts/linux_quickstart.sh
```

Set `PARALLAX_DATA_DIR` or `PARALLAX_PORT` when you need a different output
directory or port. Existing case directories are preserved automatically.

For the additional Streamlit investigation interface, open another activated terminal:

```bash
parallax streamlit --data data/video-demo --port 8501
```

Open **http://127.0.0.1:8501**. Both interfaces read the same case; refresh after changing analyst feedback in the other interface.

To validate the Linux container with runtime networking disabled:

```bash
docker build -t parallax .
docker run --rm --network none parallax
docker run --rm --network none parallax parallax demo --data /tmp/linux-demo --entities 160
```

The image build needs internet access to provision dependencies. The two run commands do not. Container validation status is recorded in `docs/SUBMISSION.md`.

Ubuntu prerequisites, if Python and venv are absent:

```bash
sudo apt-get update
sudo apt-get install python3 python3-venv python3-pip
```

The installer uses CPU PyTorch on Linux. If your selected Python has no compatible dependency wheels, use Python 3.12. macOS Apple Silicon and Linux wheelhouses are not interchangeable.

## Offline target

On an internet-connected machine matching the target OS, architecture and Python version:

```bash
bash scripts/prepare_offline.sh
```

Transfer the repository and generated wheelhouse. Follow the wheel manifest verification instructions in README.md, then:

```bash
bash scripts/install.sh --offline /absolute/path/to/wheelhouse
source .venv/bin/activate
parallax demo --data data/offline-demo --entities 160
parallax serve --data data/offline-demo --port 8877
```

Installation downloads dependencies unless using the offline wheelhouse. Analysis runs locally afterward. GeoIP requires separately obtained local Country/ASN MMDB files; never imply their absence is suspicious.

MaxMind requires a free account and license key for GeoLite2 downloads. After
accepting its license, download without placing credentials in Git:

```bash
export MAXMIND_ACCOUNT_ID='your-account-id'
export MAXMIND_LICENSE_KEY='your-license-key'
bash scripts/download_geolite.sh data/geolite2
parallax ingest input.json --db case.sqlite \
  --country-db data/geolite2/GeoLite2-Country.mmdb \
  --asn-db data/geolite2/GeoLite2-ASN.mmdb
```

The repository intentionally does not redistribute a GeoLite2 database or
invent a substitute MMDB. The source and license notice must travel with the
offline copy.

## GitHub handoff

Source, tests, scripts, docs and the reviewed synthetic submission sample belong in Git. Generated case databases, private signing keys, virtual environments and wheelhouses are ignored. Do not copy a generated case folder to GitHub.

After configuring the intended repository:

```bash
git remote add origin YOUR_GITHUB_REPOSITORY_URL
git push -u origin HEAD
```

Your teammate clones the intended repository, checks out the pushed branch and runs the installation commands above. Workflow templates are in `docs/workflows/`; copy them to `.github/workflows/` and push using a credential allowed to update workflows. A workflow template alone is not proof of a passing Linux run.
