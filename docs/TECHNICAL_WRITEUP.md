# PARALLAX technical write-up

## Abstract

PARALLAX is an offline Bitcoin transaction forensics workbench for NTRO Problem
Statement 26146. It correlates blockchain metadata with network observations,
preserves an auditable evidence trail, and ranks investigative leads for human
review. It is designed for reproducible analysis on a Linux or macOS analyst
workstation after dependencies and local reference databases have been staged.

## Problem and design goals

Bitcoin investigations commonly separate transaction flow from the network
observations that surrounded a relay. PARALLAX represents both layers in one
bounded graph. Its design goals are: accept bulk CSV, JSON, JSONL, and XML;
never silently discard malformed evidence; distinguish an observed relay from
wallet ownership; combine deterministic rules with trained models; explain each
ranked lead; and export a verifiable case package.

## Processing flow

1. **Ingest.** Records are streamed rather than loaded as one large object.
   Known aliases are mapped to a canonical schema, timestamps are normalized to
   UTC, and monetary values become integer satoshis.
2. **Evidence capture.** The original file is copied into the case evidence
   store. Each raw record and normalized record is hashed; audit entries form a
   previous-hash chain. Invalid rows are quarantined with their raw payload and
   reason.
3. **Enrichment.** Country and ASN lookups use operator-supplied local GeoLite2
   MMDB files. No lookup is made over the network during analysis. Provenance
   records include the MMDB hashes.
4. **Resolution and graph.** Common-input ownership and conservative change
   heuristics create wallet hypotheses. Wallet, transaction, and IP nodes are
   connected through financial flow and weak observed-relay associations.
5. **Features.** Structural features include degree and seed distance. Economic
   features include amount distribution, round-number ratio, and fee variation.
   Temporal features include interval entropy, hour-of-day activity, and
   behavioral changepoints.
6. **Detection.** Rules identify peeling, fan-out/fan-in, address reuse, and
   mixer-like signatures. Isolation Forest supplies chain-only and fused anomaly
   rankings. A native PyTorch GraphSAGE model adds graph context when explicit
   training labels exist. Ruptures PELT identifies behavior shifts when history
   is sufficient.
7. **Fusion.** The Fracture Index is a configured weighted sum of taint,
   behavioral link, timing, address reuse, and network exposure. Missing
   evidence contributes zero and is reported through coverage; the score is a
   priority category, not a probability of criminality.
8. **Review and export.** The dashboard shows the score components, SHAP
   contributions, rule-hit TXIDs, supporting graph, uncertainty, taint
   haircut, endpoint candidates, and analyst review controls. A signed PDF/ZIP
   dossier can be checked by a standalone verifier without importing PARALLAX.

## Model and explainability

Isolation Forest is trained over address profiles and calibrated only with
separate synthetic calibration data when available. The chain-only baseline
measures the incremental value of network features. GraphSAGE is intentionally
small and native to PyTorch so the offline dependency surface remains clear.
Tree SHAP explains the Isolation Forest path-length response; it does not imply
causality. Rule evidence is linked to actual transaction IDs, and plain-language
notes are generated only from fields present in the evidence graph.

## Integrity and review controls

The source hash, row hashes, audit-chain head, model hash, and normalized records
are retained. A dossier contains a signed manifest, selected records, graph,
score snapshot, PDF, and detached PDF signature. The trusted public key and
original audit log should be retained separately. False-positive dismissal is
explicit, reasoned, idempotent, and invalidates stale evaluation before a new
ranking is used.

## Validation results

The supplied synthetic PS26146 data contains 4,303 transactions. Its generator
stores aggregate input amounts for some multi-input rows and has five tiny
rounding overflows; `scripts/normalize_dataset.py` preserves the original hash
and records those repairs before strict ingestion. The normalized run accepted
all 4,303 records and scored 6,032 wallet profiles. With the supplied GeoLite2
Country and ASN databases, 4,232 observations received country matches and
3,591 received ASN matches.

The generator ground truth placed 20 positive profiles in the top 20 ranked
profiles. This is a development benchmark because the labels and data were
generated together. The fixed Fracture high band did not cross 60 in this run;
that threshold result is reported rather than tuned after seeing labels.

The adaptive harness measures peel-chain, fan-out, mixer-hop, and timing-jitter
evasion across mutation rounds. Results are retained even when recall falls,
because the purpose is to expose failure modes for future labelled-data
calibration. No real seized data, live intercepts, or real-world attribution is
claimed.

## Reproduction

```bash
bash scripts/install.sh
source .venv/bin/activate
python -m pytest -q
parallax demo --data data/demo --entities 160
parallax serve --data data/demo --port 8877
```

For the supplied dataset:

```bash
python scripts/normalize_dataset.py parallax_dataset.json \
  --out data/normalized.json --manifest data/normalization.json
parallax ingest data/normalized.json --db data/case.sqlite \
  --country-db GeoLite2-Country.mmdb --asn-db GeoLite2-ASN.mmdb
parallax score --db data/case.sqlite --model data/demo/model
```

## Scope and limitations

An observed IP is not proof of wallet ownership: NAT, VPN, Tor, shared hosting,
relays, and time skew are alternative explanations. Taint is an address-account
approximation because the supplied metadata has no UTXO outpoints. Endpoint
labels are unverified candidates, never KYC identities. The supplied dataset is
synthetic; independent NTRO records and a documented external topology are
still needed for operational validation. Linux acceptance requires a completed
run on a connected Linux host; the Dockerfile and offline runtime commands are
included for that handoff.
