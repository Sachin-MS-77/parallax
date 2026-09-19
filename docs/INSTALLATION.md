# Mac development and Linux teammate handoff

Use Python 3.12 (tested locally); Python 3.11+ is declared supported. No Linux VM is needed to develop or record the Mac demo.

## On either Mac or Ubuntu/Linux

Open a terminal in the cloned PARALLAX repository:

```bash
bash scripts/install.sh
source .venv/bin/activate
python -m pytest -q
parallax demo --data data/video-demo --entities 160
parallax serve --data data/video-demo --port 8877
```

Open **http://127.0.0.1:8877**. The demo command creates training, calibration and held-out synthetic test splits, trains models and attaches evaluation. It refuses to overwrite an existing demo directory: choose a new directory when repeating. Keep the terminal running; press Ctrl+C to stop.

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

## GitHub handoff

Only source, tests, scripts and docs belong in Git. Generated cases, private signing keys, virtual environments and wheelhouses are ignored. Do not copy a generated case folder to GitHub.

After configuring the intended repository:

```bash
git remote add origin YOUR_GITHUB_REPOSITORY_URL
git push -u origin HEAD
```

If origin already exists, inspect it with `git remote -v` before changing it. Your teammate clones that URL, checks out the pushed branch and runs the installation commands above. The included GitHub Actions workflow runs Mac and Ubuntu tests after pushing; a workflow file alone is not proof of a passing Linux run.
