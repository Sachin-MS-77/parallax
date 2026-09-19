# Feature status — September 19, 2026

**A working offline research prototype exists. The entire aspirational plan is not fully completed or independently validated.** UI demonstrations and passing unit tests do not establish real-world investigative performance.

| Planned capability | Implementation and evidence | Remaining limitation |
|---|---|---|
| CSV/JSON/XML bulk ingestion | Streaming readers, aliases, integer satoshis, validation, quarantine; format tests | Full graph/ML processing remains in memory; no large-scale benchmark claim |
| Evidence log | Source SHA-256, record hashes, chained audit log, materialized-state and source verification | Application append-only behavior; not immutable storage or trusted external timestamping |
| Schema mapping | Known aliases and unknown-field reports | No interactive field-remapping editor |
| Offline GeoIP/ASN and Tor | Local MMDB enrichment and dated local Tor snapshot support | Real MMDB files must be supplied; not included or validated here |
| Entity resolution | Conservative common-input clusters, change candidates, UTC normalization | Change candidates are hypotheses, not automatically merged; no verified owners |
| Unified graph | Address, candidate wallet entity, transaction and IP views; weak shared-relay associations | Display bounded for responsiveness; observed relay is not origin attribution |
| Features and rules | Structural, temporal, economic, reuse, fan patterns, peeling and collaborative-spend heuristics | Mixer-like shape is not a validated mixer-service identifier; seed distance is not amount-weighted taint |
| Isolation Forest | Working trained model, chain-only baseline, fused features | Synthetic calibration does not establish operational reliability |
| GraphSAGE | Working trained two-layer classifier with explicit synthetic labels | No RGCN/HGT; neighborhood sampling and synthetic training constrain conclusions |
| Fusion score | Weighted components, missing-input handling, calibrated priority threshold | Heuristic priority, not probability of criminality; evidence completeness is not a statistical confidence interval |
| Explainability | Tree SHAP, rule evidence, highlighted graph and caveats | SHAP explains Isolation Forest path length, not causality |
| Dashboard | Redesigned charts, graph layers, search, filters, reviews, source integrity, exports | Local analyst workstation; no multi-user authentication or case-management server |
| Signed dossier | PDF, JSON, records and Ed25519-signed manifest; detached PDF signature | Export is selected-address centered, not a complete aggregated cluster dossier; not an Adobe/PAdES certificate |
| Evaluation | Held-out synthetic Precision@20, recall, FPR, baselines, calibration | Actual NTRO transaction dataset and independent real-world labels not tested |
| Adversarial simulation | Strategy mutation and per-scenario reports | Limited evasion families; does not cover every peel/mixer technique |
| Published case pattern | Synthetic replay inspired by publicly documented laundering behavior | Not a reconstruction from real case transaction records; not external validity |
| Feedback / drift | Explicit feedback retraining, holdout Brier; distribution diagnostic | Diagnostic drift threshold, not comprehensive validated drift monitoring |
| Linux delivery | Linux-compatible Python package, installer, Dockerfile and Ubuntu CI workflow | Linux execution must be confirmed by CI or teammate; only Mac execution checked locally |
| Offline runtime | Local assets/models; no runtime API or CDN dependencies; blocked-network inference test | Online dependency provisioning or matching offline wheelhouse required first |

The 90-second video can credibly demonstrate the core analysis-to-evidence workflow. Keep extended verification and installation evidence available for questions. Do not present optional stretch work or externally dependent features as fully verified.
