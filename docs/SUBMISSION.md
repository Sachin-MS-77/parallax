# PARALLAX submission evidence

## Measured local run

Date: 25 September 2026. Host: macOS 26.3 / arm64, Python 3.14.0.
The demonstration generated separate train/calibration/test source files,
trained Isolation Forest and GraphSAGE, scored 160 test profiles, evaluated
them and exported a signed dossier. Runtime: 11.217 seconds; peak RSS: 475.55 MB.

| Detector | Measured P@20 | Precision at detector threshold | Recall |
|---|---:|---:|---:|
| Rules | 7/20 | 28.8% | 53.1% |
| Chain-only Isolation Forest | 15/20 | 88.9% | 25.0% |
| Fused Isolation Forest | 16/20 | 100% | 28.1% |
| Requested Fracture Index | 13/20 | 0% (no high alerts) | 0% |
| GraphSAGE | 20/20 | 100% | 90.6% |

These results apply only to project-generated fixtures. The Fracture Index uses
the requested fixed >60 high threshold. In this unseeded fixture there is no
taint evidence and limited reuse/relay evidence, so no score crosses 60. The
ranked queue still exists. Do not claim the GraphSAGE result is the ensemble's
result or change the threshold after inspecting test labels.

## Adaptive validation

Separate seed-assisted simulation: 16 actors, including 8 positive actors.
Seed-origin addresses are excluded from actor-level detection.

| Round | Detected positives | Recall | Peel recall | Fan-out recall | Mixer recall | Jitter recall |
|---|---:|---:|---:|---:|---:|---:|
| Baseline | 7/8 | 87.5% | 100% | 100% | 100% | 50% |
| Mutation 1 | 2/8 | 25% | 0% | 0% | 100% | 0% |
| Mutation 2 | 0/8 | 0% | 0% | 0% | 0% | 0% |

The first mutation round changed seven flagged actors; the second changed two.
The failure illustrates the limits of fixed heuristic weights under evasion.
Potential improvements require independently labelled data and validation of
temporal/path features; they are not silently claimed as implemented fixes.

## Reproduce

```bash
source .venv/bin/activate
python -m pytest -q
parallax demo --data data/submission-new --entities 160
parallax adversarial --model data/submission-new/model --out data/stress-new --rounds 3
python scripts/package_submission.py --demo data/submission-new --stress data/stress-new --out submission/new-run
python scripts/verify_dossier_standalone.py submission/new-run/sample-case.zip submission/new-run/original-audit.jsonl --trusted-key submission/new-run/signer-public-key.txt
```

The package command exports a seeded synthetic fan-out lead and runs the
independent verifier. Full audit, record, signature and scoring-snapshot checks
passed for the included sample. The original log and key are bundled for easy
reproduction, but in actual use they must be retained independently.

## Verification and external status

- 24 automated tests passed on macOS, including Streamlit rendering and endpoint evidence.
- Full demo test runs with socket connection attempts blocked.
- Styled dashboard and Streamlit load locally; live evasion returns measured changes.
- Actual NTRO dataset and independent Elliptic case topology remain unavailable.
- Linux container validation is prepared in `Dockerfile`, but this Mac run could not complete the 159 MB aarch64 CPU-PyTorch download within the available build window. A teammate should run the documented Docker commands on a connected Linux host, then repeat the two `--network none` runtime checks.

For recording, use the [timed script](DEMO_SCRIPT.md). The UI now also includes
live evasion and Fracture weight feedback; reserve an extended demonstration for
these instead of rushing all functionality into 90 seconds.
