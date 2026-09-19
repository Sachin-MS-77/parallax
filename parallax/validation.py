"""Adaptive synthetic stress testing and a sourced case-pattern reconstruction."""
import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .features import build_features
from .ingest import ingest
from .model import load_model, predict
from .storage import connect, set_meta, file_hash
from .synthetic import generate, btc
from .evaluate import metrics

CASE_SOURCE='https://www.justice.gov/archives/opa/pr/two-arrested-alleged-conspiracy-launder-45-billion-stolen-cryptocurrency'


def adaptive(model_dir, out, rounds=3, entities=80):
    out=Path(out)
    if out.exists(): raise ValueError('Use a new validation directory to preserve previous runs')
    out.mkdir(parents=True)
    generate(out/'fixtures','test',entities,seed=919)
    records=[json.loads(line) for line in (out/'fixtures/test.jsonl').read_text().splitlines()]
    labels=json.loads((out/'fixtures/test-labels.json').read_text())['labels']
    bundle,manifest=load_model(model_dir)
    threshold=manifest.get('priority_threshold',80)
    report={'scope':'Adaptive development stress test, not held-out performance or external validity',
            'model_sha256':manifest['artifact_sha256'],'threshold':threshold,'rounds':[]}
    for iteration in range(rounds):
        path=out/f'round-{iteration}.jsonl'
        path.write_text(''.join(json.dumps(r)+'\n' for r in records))
        dbpath=out/f'round-{iteration}.sqlite'; ingest(path,dbpath)
        db=connect(dbpath); profiles=build_features(db); db.close()
        alerts=predict(profiles,bundle,manifest,explanations=False)
        alerts.sort(key=lambda a:a['address'])
        y=[labels[a['address']]['label'] for a in alerts]; scores=[a['priority']/100 for a in alerts]
        per={}
        for family in sorted({x['scenario'] for x in labels.values() if x['label']}):
            indices=[i for i,a in enumerate(alerts) if labels[a['address']]['scenario']==family or y[i]==0]
            per[family]=metrics([y[i] for i in indices],[scores[i] for i in indices],threshold/100)
        flagged={a['address'] for a in alerts if a['priority']>=threshold and labels[a['address']]['label']}
        report['rounds'].append({'round':iteration,'metrics':metrics(y,scores,threshold/100),'per_technique':per,
                                 'mutated_positive_profiles':len(flagged) if iteration<rounds-1 else 0})
        if iteration==rounds-1: break
        # Simulator consults current detector output; only detected synthetic actors mutate.
        mutated=[]
        for row in records:
            r=copy.deepcopy(row); address=r['input_addresses'][0]
            if address in flagged:
                offset=int(r['txid'][:6],16)%36000
                r['timestamp']=(datetime.fromisoformat(r['timestamp'])+timedelta(seconds=offset)).isoformat()
                # Preserve values, change transaction timing and relay visibility.
                r['src_ip']=None; r['src_port']=None
                if int(r['txid'][-2:],16)%2:
                    r['dst_ip']=None; r['dst_port']=None
            mutated.append(r)
        records=sorted(mutated,key=lambda r:r['timestamp'])
    report['failure_analysis']='Compare per-technique recall across rounds; report missed actors. Timing perturbation and missing observations test capture dependence. Do not tune against the frozen test report.'
    (out/'report.json').write_text(json.dumps(report,indent=2))
    return report


def case_replay(model_dir,out):
    out=Path(out)
    if out.exists(): raise ValueError('Use a new case-replay directory')
    out.mkdir(parents=True)
    # Synthetic realization of documented automated fragmentation/layering. No real identities or TXIDs.
    rows=[]; start=datetime(2025,6,1,tzinfo=timezone.utc); current='replay_seed'; amount=100_000_000
    for i in range(6):
        fee=1000; small=1_000_000; nxt=f'replay_layer_{i}'
        rows.append({'timestamp':(start+timedelta(seconds=i*15)).isoformat(),'src_ip':'198.51.100.9','dst_ip':'203.0.113.3',
                     'src_port':23000,'dst_port':8333,'txid':hashlib.sha256(f'replay:{i}'.encode()).hexdigest(),
                     'input_addresses':[current],'output_addresses':[f'replay_fragment_{i}',nxt],
                     'input_amounts':[btc(amount)],'output_amounts':[btc(small),btc(amount-small-fee)],
                     'fee':btc(fee),'vsize':160,'script_type':'p2wpkh'})
        current=nxt; amount-=small+fee
    path=out/'case.json'; path.write_text(json.dumps(rows,indent=2)); ingest(path,out/'case.sqlite')
    db=connect(out/'case.sqlite')
    with db: set_meta(db,'seed_addresses',[{'address':'replay_seed','source':CASE_SOURCE,'status':'synthetic scenario seed'}])
    profiles=build_features(db); db.close()
    bundle,manifest=load_model(model_dir); alerts=predict(profiles,bundle,manifest,explanations=False)
    report={'source':CASE_SOURCE,'source_description':'DOJ press release, 8 February 2022; automated transactions and fragmentation/layering described in allegations',
            'scope':'Qualitative reconstruction of published behavior; invented topology and values, not recovered case data or independent external validation',
            'omitted':'Cross-chain hops, exchange account identity and darknet records are outside available Bitcoin metadata',
            'dataset_sha256':file_hash(path),'profiles':len(alerts),
            'peeling_pattern_detected':any(any(r['name']=='Peeling-chain pattern' for r in a['rules']) for a in alerts),
            'high_priority_profiles':sum(a['priority_band']=='High' for a in alerts),
            'priorities':[{'address':a['address'],'priority':a['priority'],'reason':a['reason']} for a in alerts]}
    (out/'report.json').write_text(json.dumps(report,indent=2))
    return report
