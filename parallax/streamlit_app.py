"""Local Streamlit frontend sharing the same case, scoring and evidence functions."""
import json
import sys
import tempfile
from pathlib import Path

import streamlit as st
from reportlab.graphics import renderSVG
from parallax.analysis import config
from parallax.evidence import dossier, get_alert
from parallax.graph import graph
from parallax.ingest import ingest
from parallax.model import score
from parallax.proofgraph import drawing
from parallax.storage import connect, get_meta, verify_state, file_hash, canonical, set_meta
from parallax.triage import review_case

st.set_page_config(page_title="PARALLAX", page_icon="◈", layout="wide")
data = Path(sys.argv[1] if len(sys.argv) > 1 else "data/demo").resolve()
st.title("PARALLAX · Offline investigation")
st.caption("PS 26146 · Observed relay links do not establish wallet ownership.")
if not (data/"case.sqlite").exists() or not (data/"model/manifest.json").exists():
    st.error("Generate a demo or provide a case.sqlite and trained model first.")
    st.stop()

db = connect(data/"case.sqlite")
try:
    with st.sidebar:
        st.header("Local case")
        st.caption(str(data))
        st.write("Data domain:", get_meta(db, "domain", "unknown"))
        upload = st.file_uploader("CSV, JSON, JSONL or XML metadata", type=["csv","json","jsonl","ndjson","xml"])
        if st.button("Import and score", disabled=upload is None):
            with tempfile.NamedTemporaryFile(suffix=Path(upload.name).suffix, delete=False) as f:
                source=Path(f.name); f.write(upload.getvalue())
            try:
                result=ingest(source, data/"case.sqlite")
                with db:
                    set_meta(db,"domain","unknown"); set_meta(db,"evaluation",None)
                score(data/"case.sqlite", data/"model")
                st.success(str(result))
            finally: source.unlink(missing_ok=True)
            st.rerun()
    rows=[get_alert(db,r[0]) for r in db.execute("SELECT address FROM alerts ORDER BY priority DESC,address")]
    metrics=st.columns(4)
    metrics[0].metric("Transactions", db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0])
    metrics[1].metric("Relay observations", db.execute("SELECT COUNT(*) FROM observations").fetchone()[0])
    metrics[2].metric("Address profiles", len(rows))
    metrics[3].metric("Quarantined", db.execute("SELECT COUNT(*) FROM quarantine").fetchone()[0])
    leads, validation, evidence=st.tabs(["Investigative leads","Validation & evasion","Evidence integrity"])
    with leads:
        if rows:
            st.dataframe([{"Address":a["address"],"Fracture Index":a["priority"],
                           "Band":a.get("confidence_band",a["priority_band"]),
                           "Evidence completeness":a["evidence_quality"],"Status":a["status"]} for a in rows],
                         hide_index=True, width="stretch")
            address=st.selectbox("Select address", [a["address"] for a in rows])
            alert=get_alert(db,address)
            st.subheader("Evidence-derived case note")
            st.write(alert.get("case_note",alert["reason"]))
            st.caption("Score bands describe priority; they are not calibrated statistical confidence.")
            layer=st.radio("Graph layer",["fused","chain","network"],horizontal=True)
            neighborhood=graph(db,address,layer,limit=6)
            st.image(renderSVG.drawToString(drawing(neighborhood)))
            st.caption(f"{len(neighborhood['nodes'])} nodes · {len(neighborhood['edges'])} links; bounded evidence view")
            st.subheader("Model explanation")
            if alert["explanations"]:
                st.bar_chart([{"feature":e["feature"],"path_length":e["shap_path_length"]}
                              for e in alert["explanations"]],x="feature",y="path_length")
            st.caption("Negative SHAP path-length contributions increase Isolation Forest anomalousness.")
            st.json({"components":alert["subscores"],"rules":alert["rules"],
                     "changepoints":alert.get("behavioral_drift"),
                     "taint":alert.get("taint"),"cash_out_candidates":alert.get("cashout_targets")},expanded=False)
            with st.form("review"):
                status=st.selectbox("Review status",["New","Triaging","Escalated","Dismissed"])
                reason=st.text_area("Reason")
                false_positive=st.checkbox("Confirmed false positive: update weights on dismissal")
                submitted=st.form_submit_button("Save review")
            if submitted:
                try:
                    st.session_state["review_result"]=review_case(data,address,status,reason,false_positive)
                    st.rerun()
                except ValueError as exc: st.error(str(exc))
            if "review_result" in st.session_state:
                st.json(st.session_state["review_result"],expanded=False)
            if st.button("Prepare signed cluster dossier"):
                st.session_state["dossier"]=(address,dossier(db,address,data/"keys"))
            prepared=st.session_state.get("dossier")
            if prepared and prepared[0]==address:
                st.download_button("Download signed PDF + evidence",prepared[1],"parallax-case.zip","application/zip")
        else: st.info("No scored profiles available.")
    with validation:
        report=get_meta(db,"evaluation")
        if report:
            baseline=report["baselines"]["fused_priority"]; k=baseline["k_used"]
            st.metric("Measured synthetic Precision@K",
                      f"{round(baseline['precision_at_20']*k)}/{k} top alerts")
            st.caption(report["scope"])
            st.dataframe([{"baseline":name,**values} for name,values in report["baselines"].items()])
            st.json(report["per_scenario"],expanded=False)
        else: st.info("No current held-out evaluation; imports and feedback invalidate prior results.")
        st.subheader("Configured Fracture Index weights")
        st.json(config(db))
        if st.button("Attempt Evasion"):
            from parallax.adversary import attempt
            with st.spinner("Running one round in a separate synthetic sandbox"):
                try: st.session_state["evasion"]=attempt(data)
                except ValueError as exc: st.error(str(exc))
        if "evasion" in st.session_state:
            result=st.session_state["evasion"]
            before={a["actor"]:a for a in result["before"]["actors"]}
            st.caption(result["scope"])
            st.dataframe([{"actor":a["actor"],"technique":a["technique"],
                           "before":before[a["actor"]]["priority"],"after":a["priority"],
                           "change":a["priority"]-before[a["actor"]]["priority"]} for a in result["after"]["actors"]])
            st.json(result["mutations"],expanded=False)
    with evidence:
        if st.button("Verify Evidence Integrity"):
            result=verify_state(db)
            intact=all(Path(r["stored_path"]).is_file() and file_hash(r["stored_path"])==r["hash"]
                       for r in db.execute("SELECT * FROM sources"))
            if result["valid"] and intact: st.success("Integrity verified: audit chain, records and source files")
            else: st.error("Integrity verification failed")
            st.json({**result,"sources_intact":intact})
        st.download_button("Download original audit log",
            "".join(canonical(dict(r))+"\n" for r in db.execute("SELECT * FROM audit ORDER BY seq")),
            "original-audit.jsonl","application/x-ndjson")
        st.dataframe([dict(r) for r in db.execute("SELECT source_hash,source_row,error FROM quarantine LIMIT 100")])
finally:
    db.close()
