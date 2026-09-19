import base64
import copy
import io
import json
import socket
import zipfile

import numpy as np
import pytest
from fastapi.testclient import TestClient
from cryptography.exceptions import InvalidSignature

from parallax.cli import demo
from parallax.evidence import verify_dossier, verify_pdf
from parallax.features import build_features, matrix
from parallax.graph import graph
from parallax.intelligence import context
from parallax.ingest import ingest
from parallax.model import load_model, predict
from parallax.server import create_app
from parallax.storage import connect, verify_state, get_meta
from parallax.synthetic import generate
from parallax.validation import adaptive, case_replay


@pytest.fixture(scope='module')
def case(tmp_path_factory):
    path=tmp_path_factory.mktemp('case')
    demo(path,60)
    return path


def test_all_formats_deduplicate_without_duplicating_money(tmp_path):
    generate(tmp_path/'fixtures','test',10)
    accepted = {}
    for ext in ('json','csv','xml'):
        dbpath=tmp_path/f'{ext}.sqlite'
        result=ingest(tmp_path/f'fixtures/sample.{ext}',dbpath)
        accepted[ext]=result['accepted']
        assert result['quarantined']==0 and result['accepted']>0
        db=connect(dbpath)
        assert db.execute('SELECT COUNT(DISTINCT txid) FROM transactions').fetchone()[0]>0
        assert verify_state(db)['valid']
        db.close()
    assert len(set(accepted.values()))==1


def test_quarantine_unknown_fields_and_tor_interval(tmp_path):
    generate(tmp_path/'fixtures','test',1)
    row=json.loads((tmp_path/'fixtures/test.jsonl').read_text().splitlines()[0])
    row['mystery_field']='preserve in source'
    bad=copy.deepcopy(row); bad['txid']='broken'
    path=tmp_path/'input.json';path.write_text(json.dumps([row,bad]))
    tor=tmp_path/'tor.json';tor.write_text(json.dumps({'valid_from':'2025-01-01T00:00:00Z','valid_until':'2025-12-31T23:59:59Z','ips':[row['src_ip']]}))
    result=ingest(path,tmp_path/'case.sqlite',tor_snapshot=tor)
    assert result['accepted']==1 and result['quarantined']==1
    db=connect(tmp_path/'case.sqlite')
    assert 'mystery_field' in get_meta(db,'schema_report')['unmapped_fields']
    assert json.loads(db.execute('SELECT record_json FROM observations').fetchone()[0])['tor_exit'] is True
    db.close()


def test_shared_ip_is_not_ownership_and_graph_has_layers(case):
    db=connect(case/'case.sqlite');c=context(db)
    assert all(len(e['members'])==1 for e in c['entities'])
    address=db.execute('SELECT address FROM alerts LIMIT 1').fetchone()[0]
    fused=graph(db,address,'fused');chain=graph(db,address,'chain')
    assert fused['ownership_claims']==0
    assert not any(n['kind']=='ip' for n in chain['nodes'])
    assert all(e['certainty']=='observed_relay_only' for e in fused['edges'] if e['kind'].startswith('observed_'))
    db.close()


def test_shap_explains_forest_and_graphsage_is_trained(case):
    bundle,manifest=load_model(case/'model')
    assert bundle['graph']['training_loss']>=0 and manifest['graph_labels_sha256']
    db=connect(case/'case.sqlite');rows=build_features(db)[:3];db.close()
    alerts=predict(rows,bundle,manifest)
    assert all(a['graph_score'] is not None for a in alerts)
    # Isolation Forest anomaly score is 2 ** (-expected path length / c(max_samples)).
    from sklearn.ensemble._iforest import _average_path_length
    for a in alerts:
        path_length=a['shap_base_path_length']+sum(a['shap_values'])
        raw=2**(-path_length/_average_path_length([bundle['models']['fused'].max_samples_])[0])
        assert abs(raw-a['raw_anomaly_score'])<1e-5
        assert abs(sum(v['weight'] for v in a['subscores'].values())-1)<1e-9


def test_case_signature_and_pdf_tamper_detection(case,tmp_path):
    key=(case/'signer-public-key.txt').read_text()
    assert verify_dossier(case/'sample-case.zip',key)['signer_trusted']
    with zipfile.ZipFile(case/'sample-case.zip') as z:
        pdf=z.read('report.pdf');sig=z.read('report.pdf.sig')
    assert pdf.startswith(b'%PDF')
    (tmp_path/'report.pdf').write_bytes(pdf);(tmp_path/'report.pdf.sig').write_bytes(sig)
    assert verify_pdf(tmp_path/'report.pdf',tmp_path/'report.pdf.sig',case/'signer-public-key.txt')['valid']
    (tmp_path/'report.pdf').write_bytes(pdf+b'changed')
    with pytest.raises(InvalidSignature):verify_pdf(tmp_path/'report.pdf',tmp_path/'report.pdf.sig',case/'signer-public-key.txt')


def test_dashboard_security_and_review(case):
    with TestClient(create_app(case)) as client:
        index=client.get('/')
        assert index.status_code==200
        assert 'src="/static/app.js"' in index.text and 'onclick=' not in index.text
        assert client.get('/static/app.js').status_code==200
        assert client.get('/api/summary',headers={'host':'evil.example'}).status_code==403
        assert client.post('/api/review',headers={'origin':'https://evil.example'},json={}).status_code==403
        address=client.get('/api/alerts').json()['items'][0]['address']
        assert client.post('/api/review',json={'address':address,'status':'Triaging','reason':'Checking source evidence'}).status_code==200
        assert client.get('/api/alert',params={'address':address}).json()['status']=='Triaging'
        assert client.get('/api/integrity').json()['valid']


def test_materialized_evidence_tampering_is_detected(case):
    db=connect(case/'case.sqlite')
    db.execute('UPDATE flows SET amount_sats=amount_sats+1 WHERE rowid=(SELECT rowid FROM flows LIMIT 1)')
    assert not verify_state(db)['valid']
    db.rollback();db.close()


def test_external_network_unavailable_during_inference(case,monkeypatch):
    def forbidden(*args,**kwargs): raise AssertionError('Unexpected network connection')
    monkeypatch.setattr(socket.socket,'connect',forbidden)
    bundle,manifest=load_model(case/'model')
    db=connect(case/'case.sqlite');rows=build_features(db)[:4];db.close()
    assert len(predict(rows,bundle,manifest))==4


def test_published_pattern_reconstruction(case,tmp_path):
    report=case_replay(case/'model',tmp_path/'replay')
    assert report['peeling_pattern_detected']
    assert 'justice.gov' in report['source']
