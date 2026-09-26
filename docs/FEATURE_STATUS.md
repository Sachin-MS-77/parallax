# Working-plan status — 25 September 2026

Implemented features are mapped to the supplied 13-stage plan below. “Implemented”
means working code with stated scope; it does not mean independent forensic validation.

| Step | Delivered implementation | Scope or remaining dependency |
|---|---|---|
| 1. Ingestion and evidence | Streaming CSV/JSON/XML; bounded Polars batches and DuckDB staging; SQLite evidence store; source/row hashes and audit chain | Full feature/graph stages remain in memory. Append-only application log needs a separately retained anchor |
| 2. Mapping and parsing | Aliases, explicit mapping file, UTC, satoshis, network/blockchain fields, unknown-field report | Unknown schemas may require an operator mapping |
| 3. Entity resolution | Union-find common-input candidates with Meiklejohn citation; conservative collaborative-spend exclusion; quarantine and local MMDB support | Clusters are hypotheses. GeoIP databases must be supplied locally |
| 4. Unified graph | Candidate entities, addresses, transactions and observed IPs; financial flow and shared first-observation associations; layer toggle | Observed relay is not transaction origin. Views are bounded |
| 5. Features | Degree, seed distance, amounts, round-number ratio, fee-rate variation, interval entropy and 24-hour histogram | Fee-rate feature measures within-profile variation, not comparison to a live fee market |
| 6. Detection | Rules, trained Isolation Forest, ruptures PELT behavioral changepoints, trained GraphSAGE | GraphSAGE uses native PyTorch mean aggregation, not PyG; no fallback needed for the converged tested model. Short histories return insufficient-history |
| 7. Taint | Chronological amount-weighted haircut estimate with 0.9 decay, synthetic seeds, local CSV references and historical OFAC sample | No UTXO outpoints: address-account approximation. Historical OFAC sample is not a current complete sanctions list |
| 8. Endpoints | Bounded downstream candidates from local exchange references or terminal nodes with multiple funders | KYC/account identity cannot be inferred from deposit sizes; candidates are explicitly unverified |
| 9. Fracture Index | Exact five-component configured weighted sum; Low/Moderate/High score bands; missingness coverage; audited weight updates | Bands are priority categories, not calibrated certainty. Missing evidence contributes zero and can suppress high alerts |
| 10. Explainability | SHAP, rule TXIDs, evidence-derived notes, supporting path subgraph and uncertainty | Evidence-selected graph is not a mathematically minimum graph; notes avoid claims not supported by fields |
| 11. Adversarial harness | Peel, fan-out, mixing and jitter actors; detector-triggered fresh-address/timing/mixer/co-input mutations; all rounds and failures reported | Existing published-pattern replay is DOJ-inspired synthetic data. Real Elliptic topology cross-check remains unavailable |
| 12. Independent verification | Cluster PDF/JSON, graph SVG, complete selected records, score snapshot, detached signatures; standalone verifier against original audit | Requires a separately trusted key/log; cannot certify truth of original metadata or legal admissibility |
| 13. Dashboard | Styled local dashboard plus Streamlit; ranked leads, SHAP, drift, taint, endpoint candidates, case notes, graph layers, temporal filtering, edge provenance, counterfactual evidence lift, intake preview, competing hypotheses, evasion technique filtering, integrity badge and triage | Single local analyst workstation, not a multi-user case-management server |

## Submission evidence

The `submission/2026-09-25/` folder contains measured evaluation, adaptive report,
sample signed PDF/ZIP, original audit log, public key, independent verifier and
verification result. No private key is included. The sample dossier comes from
the explicitly seeded simulation; it must not be described as an NTRO real case.

## External requirements still outstanding

1. **Official NTRO metadata:** the PS26146 README states the official dataset
   link is nil. The supplied synthetic JSON/CSV has now been ingested and scored;
   it must be labelled as synthetic generator data in the submission.
2. **Independent real topology:** no Elliptic edge list or documented case
   transaction graph was supplied. Public research is cited, not fabricated.
3. **GeoIP coverage:** provide licensed local MMDB files before claiming enriched
   country/ASN coverage.
4. **Linux acceptance:** the operator has reported successful native Kali server
   startup and listed the generated demo artifacts. Test logs, integrity results,
   benchmark contents and browser screenshots are still needed; follow
   [Linux acceptance capture](LINUX_ACCEPTANCE.md). Docker network-isolated
   execution remains unverified.
