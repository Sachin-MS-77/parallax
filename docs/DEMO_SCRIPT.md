# PARALLAX — two-minute presentation

Rehearse at approximately 125–135 words/minute. Use one PPT slide for the first 30 seconds, then switch to the already-running browser. This script demonstrates the core flow; it cannot prove every feature in 90 seconds.

## 0:00–0:30 — PPT (one slide)

Slide title: **PARALLAX: Offline Bitcoin Investigation**

Three points: **CSV / JSON / XML → fused evidence graph → explainable leads**. Below: **Isolation Forest + GraphSAGE · Evidence integrity · Human review**.

Say:

“Bitcoin investigations involve two disconnected views: transactions on the blockchain and observations from the network. PARALLAX brings them together in an offline investigation workbench for NTRO’s problem statement 26146. It ingests bulk metadata, links addresses, transactions and observed IPs, and uses machine learning to prioritize explainable leads. Analysts can inspect the supporting evidence and export a signed case dossier.”

## 0:30–0:48 — Dashboard overview

Show the summary cards, transaction chart and comparison panel.

“This is our synthetic demonstration dataset. The dashboard shows transaction volumes, preserved relay observations and prioritized address profiles. These charts come from the loaded case. The comparison measures chain-only and fused detection on held-out synthetic data.”

## 0:48–1:10 — Lead and graph

Select the first lead. Scroll to Connected evidence. Switch Blockchain only → Network only → Fused view.

“Selecting a lead opens its evidence graph. We can switch between blockchain, network and fused views. This connects financial activity with observed relay behavior. Shared IP addresses are treated as weak associations, because a relay or shared network does not prove wallet ownership.”

## 1:10–1:30 — Explainability and review

Point to score, scoring components, SHAP and rule evidence. Show analyst decision without needing to type during recording.

“The priority score is supported by model contributions, rule hits and explicit uncertainty. SHAP explains the Isolation Forest response, while the evidence panel shows why the lead deserves review. Analysts can record a decision and preserve their reasoning in the audit log.”

## 1:30–1:45 — Validation

Click Model validation. Show the baselines table.

“We report Precision at twenty, recall and false positives instead of relying on accuracy alone. These results are synthetic benchmarks, not evidence of operational accuracy. Separate stress tests explore how detection changes under evasion.”

## 1:45–2:00 — Integrity and export

Click Evidence & sources → Verify evidence now. Return to leads, click Signed PDF + evidence.

“Finally, we verify the evidence trail and export a signed PDF and evidence package. PARALLAX runs locally after installation, keeping analysis offline. It supports investigators with reproducible leads; final attribution remains a human decision.”

## Recording preparation

1. Run the installation and demo commands in INSTALLATION.md before recording.
2. Use a fresh generated demo, not imported unlabelled metadata, for the evaluation segment.
3. Open the dashboard at 100% browser zoom. Hide unrelated tabs and notifications.
4. Rehearse graph switching and scrolling. Have an exported PDF ready in a separate tab if the download takes time.
5. Do not install packages, train models or run stress tests inside the 90-second demo.
6. Do not say “all features are proven,” “100% accurate,” “identifies the criminal,” or “legally certified.”
7. If citing a numerical result, read it from the current run. Seeds, parameters and future versions can change results.

## Optional extended proof, outside the two minutes

Show ingestion of CSV/JSON/XML; a malformed row in quarantine; a saved analyst review; ZIP/PDF signature verification; adaptive stress-test JSON; GraphSAGE training manifest; and an offline runtime test. GeoIP needs separately supplied local MMDB files. Feedback fitting requires explicit labels. See FEATURE_STATUS.md for remaining limitations.
