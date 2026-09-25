import importlib.util
import json
import socket
import zipfile
import base64
import hashlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from parallax.analysis import changepoints, haircut, import_references, config
from parallax.adversary import attempt
from parallax.cli import demo
from parallax.ingest import ingest
from parallax.model import score
from parallax.server import create_app
from parallax.storage import connect, set_meta, canonical
from parallax.triage import review_case
from parallax.analysis import endpoints


@pytest.fixture(scope="module")
def forensic_case(tmp_path_factory):
    root=tmp_path_factory.mktemp("forensic-case")
    demo(root,40)
    return root


def test_changepoint_detects_shift_and_requires_history():
    rows=[]
    for i in range(40):
        rows.append({"txid":str(i),"first_seen":(datetime(2025,1,1,tzinfo=timezone.utc)+timedelta(hours=i)).isoformat(),
                     "chain_json":json.dumps({"output_sats":[10000 if i<20 else 10000000000],
                                             "output_addresses":["x"],"fee_sats":1000,"vsize":200})})
    assert changepoints(rows[:4])["status"]=="insufficient_history"
    result=changepoints(rows)
    assert result["status"]=="change_detected"
    assert any(abs(c["index"]-20)<=1 for c in result["changes"])


def test_haircut_proportional_amount_and_decay(tmp_path):
    rows=[]
    for i,(ins,values,outs,amounts) in enumerate([
        (["seed","clean"],["1","1"],["mid"],["1.999"]),
        (["mid"],["1.999"],["end"],["1.998"])]):
        rows.append({"txid":str(i+1)*64,"timestamp":f"2025-01-01T00:0{i}:00Z",
                     "input_addresses":ins,"input_amounts":values,"output_addresses":outs,"output_amounts":amounts})
    source=tmp_path/"flow.json";source.write_text(json.dumps(rows))
    ingest(source,tmp_path/"case.sqlite")
    db=connect(tmp_path/"case.sqlite")
    with db:set_meta(db,"seed_addresses",[{"address":"seed","source":"independent test seed"}])
    result=haircut(db);db.close()
    assert result["mid"]["fraction"]==pytest.approx(.45)
    assert result["end"]["fraction"]==pytest.approx(.405)
    assert result["end"]["sources"][0]["hops"]==2


def test_reference_csv_and_unknown_currency(tmp_path):
    path=tmp_path/"refs.csv";path.write_text("address,source,currency\nseed,test,XBT\n")
    assert import_references(tmp_path/"case.sqlite",path)["imported"]==1
    path.write_text("address,source,currency\nseed,test,ETH\n")
    with pytest.raises(ValueError):import_references(tmp_path/"case.sqlite",path)


def test_endpoint_candidates_require_support():
    ctx={"outgoing":{"a":{"b"},"b":{"terminal"}},"incoming":{"b":{"a"},"terminal":{"b","x","y"}}}
    result=endpoints("a",ctx,{})
    assert result[0]["address"]=="terminal" and result[0]["hops"]==2
    assert result[0]["label"].endswith("(unverified)")
    ctx["incoming"]["terminal"]={"b"}
    assert endpoints("a",ctx,{})==[]


def test_standalone_verifier_and_original_log_tampering(forensic_case,tmp_path):
    script=Path(__file__).parents[1]/"scripts/verify_dossier_standalone.py"
    spec=importlib.util.spec_from_file_location("independent_verifier",script)
    verifier=importlib.util.module_from_spec(spec);spec.loader.exec_module(verifier)
    assert "from parallax" not in script.read_text()
    db=connect(forensic_case/"case.sqlite")
    log=tmp_path/"original.jsonl"
    log.write_text("".join(canonical(dict(r))+"\n" for r in db.execute("SELECT * FROM audit ORDER BY seq")))
    db.close()
    assert verifier.verify(forensic_case/"sample-case.zip",log,forensic_case/"signer-public-key.txt")["valid"]
    entries=log.read_text().splitlines();row=json.loads(entries[0]);row["payload"]="{}"
    entries[0]=json.dumps(row);log.write_text("\n".join(entries)+"\n")
    with pytest.raises(ValueError):verifier.verify(forensic_case/"sample-case.zip",log,forensic_case/"signer-public-key.txt")


def test_live_evasion_and_explicit_feedback(forensic_case):
    result=attempt(forensic_case)
    assert len(result["after"]["actors"])==8
    assert set(result["after"]["per_technique"])=={"peel_chain","fan_out","mixer_hops","timing_jitter"}
    assert all(isinstance(a["priority"],(int,float)) for a in result["after"]["actors"])
    with TestClient(create_app(forensic_case)) as client:
        address=client.get("/api/alerts").json()["items"][0]["address"]
        body={"address":address,"status":"Dismissed","reason":"Explicit synthetic test false positive","false_positive":True}
        result=client.post("/api/review",json=body).json()
        assert result["weights_changed"]
        assert sum(result["weights_after"].values())==pytest.approx(1)
        assert not client.post("/api/review",json=body).json()["weights_changed"]
        assert client.get("/api/summary").json()["evaluation"] is None
        assert client.get("/api/integrity").json()["valid"]


def test_streamlit_frontend_renders(forensic_case,monkeypatch):
    from streamlit.testing.v1 import AppTest
    path=Path(__file__).parents[1]/'parallax/streamlit_app.py'
    monkeypatch.setattr(sys,'argv',[str(path),str(forensic_case)])
    app=AppTest.from_file(str(path),default_timeout=45).run()
    assert not app.exception
    assert app.title[0].value.startswith('PARALLAX')
    assert len(app.tabs)==3


def test_full_pipeline_without_network(tmp_path,monkeypatch):
    def forbidden(*args,**kwargs):raise AssertionError("Unexpected external network access")
    monkeypatch.setattr(socket.socket,"connect",forbidden)
    monkeypatch.setattr(socket,"create_connection",forbidden)
    result=demo(tmp_path/"offline",40)
    assert result["scoring"]["profiles"]==40
