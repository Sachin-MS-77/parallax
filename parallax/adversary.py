"""Deterministic, detector-responsive synthetic actors; actor-level ground truth."""
import hashlib
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from .synthetic import btc
from .storage import connect, set_meta, audit
from .ingest import ingest
from .features import build_features
from .model import load_model, predict
from .evaluate import metrics


FAMILIES = ["peel_chain","fan_out","mixer_hops","timing_jitter"]


def fixtures(states, iteration):
    records, seeds, ownership = [], [], {}
    start=datetime(2025,10,1,tzinfo=timezone.utc)
    for n,state in enumerate(states):
        rng=random.Random(940+n)
        actor=state["id"]; positive=state["label"]
        prefix=f"sim_{actor}_"; wallet=prefix+"wallet"
        source=prefix+"origin"
        if positive:
            seeds.append({"address":source,"source":"synthetic actor ground truth / "+actor,"status":"simulation only"})
        ownership[wallet]=actor
        def emit(i,ins,outs,values,outputs,seconds):
            txid=hashlib.sha256(f"{actor}:{iteration}:{i}".encode()).hexdigest()
            records.append({"timestamp":(start+timedelta(seconds=n*100000+seconds)).isoformat(),
                "src_ip":f"198.18.0.{n+1}","dst_ip":"203.0.113.1","src_port":20000+n,"dst_port":8333,
                "txid":txid,"input_addresses":ins,"output_addresses":outs,
                "input_amounts":[btc(v) for v in values],"output_amounts":[btc(v) for v in outputs],
                "fee":btc(sum(values)-sum(outputs)),"vsize":200,"script_type":"p2wpkh"})
            for a in ins:
                if a.startswith(prefix): ownership[a]=actor
        amount=100_000_000
        emit(-1,[source],[wallet],[amount+1000],[amount],0)
        seconds=1
        # Insert real additional synthetic collaborative hops when taint evasion is selected.
        for j in range(state.get("mixers",0)):
            other=prefix+f"external_mix_{j}"; nxt=prefix+f"mix_return_{j}"
            clean=amount*3
            emit(-10-j,[wallet,other],[nxt,prefix+f"mix_b_{j}",prefix+f"mix_c_{j}",prefix+f"mix_d_{j}"],
                 [amount,clean+1000],[amount]*4,seconds)
            ownership[nxt]=actor;wallet=nxt;seconds+=1
        for i in range(12):
            seconds+=rng.randrange(600,7200) if state.get("jitter") or (positive and state["family"]=="timing_jitter") else (12 if positive else 7200)
            nxt=prefix+f"fresh_{i}" if state.get("fresh") else wallet
            ownership[nxt]=actor
            outs=[nxt,prefix+f"pay_{i}"]
            continuation=int((amount-1000)*.9)
            output_values=[continuation,amount-1000-continuation]
            inputs=[wallet];values=[amount]
            if state["family"]=="fan_out" and positive:
                outs += [prefix+f"fan_{i}_{j}" for j in range(8)]
                small=(amount-1000-continuation)//9
                output_values=[continuation]+[small]*8+[amount-1000-continuation-small*8]
            if (state["family"]=="mixer_hops" and positive) or state.get("utxo"):
                # Clean co-input changes selection style without inventing an ownership fact.
                other=prefix+f"coin_{i}"; inputs.append(other);values.append(amount)
                if state.get("utxo"):
                    output_values[-1]+=amount
                else:
                    each=(2*amount-1000)//4; outs=[nxt]+[prefix+f"equal_{i}_{j}" for j in range(3)]
                    output_values=[each]*3+[2*amount-1000-3*each];continuation=each
            emit(i,inputs,outs,values,output_values,seconds)
            wallet=nxt;amount=continuation
    return sorted(records,key=lambda r:(r["timestamp"],r["txid"])),seeds,ownership


def round_run(model_dir,out,states,iteration):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    records,seeds,ownership=fixtures(states,iteration)
    source=out/f"round-{iteration}.jsonl";source.write_text("".join(json.dumps(r)+"\n" for r in records))
    dbpath=out/f"round-{iteration}.sqlite"
    ingest(source,dbpath);db=connect(dbpath)
    with db:
        set_meta(db,"seed_addresses",seeds);set_meta(db,"domain","synthetic")
        audit(db,{"event":"simulator_seeds","references":seeds})
    profiles=build_features(db);db.close()
    bundle,manifest=load_model(model_dir)
    alerts=predict(profiles,bundle,manifest,"synthetic",explanations=False)
    # Source identities supplied as seeds are not counted as detections.
    seeds_set={s["address"] for s in seeds}
    by_actor={s["id"]:[] for s in states}
    for alert in alerts:
        if alert["address"] in ownership and alert["address"] not in seeds_set:
            by_actor[ownership[alert["address"]]].append(alert)
    actors=[]
    for state in states:
        found=by_actor[state["id"]]
        best=max(found,key=lambda a:a["priority"]) if found else None
        actors.append({"actor":state["id"],"label":state["label"],"technique":state["family"],
                       "priority":best["priority"] if best else 0,"address":best["address"] if best else None,
                       "subscores":best["subscores"] if best else {},"profile_count":len(found),
                       "detected":bool(best and best["priority"]>60)})
    y=[a["label"] for a in actors];scores=[a["priority"]/100 for a in actors]
    per={}
    for family in FAMILIES:
        chosen=[a for a in actors if a["technique"]==family or not a["label"]]
        per[family]=metrics([a["label"] for a in chosen],[a["priority"]/100 for a in chosen],.60000001)
    return {"round":iteration,"actors":actors,"metrics":metrics(y,scores,.60000001),"per_technique":per}


def mutate(states,result):
    events=[]
    by_id={a["actor"]:a for a in result["actors"]}
    for state in states:
        a=by_id[state["id"]]
        if not a["label"] or not a["detected"]: continue
        options=[("address_reuse","fresh"),("timing","jitter"),("taint","mixers"),("behavioral_link","utxo")]
        candidates=[(a["subscores"].get(k,{}).get("value") or 0,k,change) for k,change in options
                    if not state.get(change) or change=="mixers" and state[change]<2]
        if not candidates: continue
        _,component,change=max(candidates)
        state[change]=state.get(change,0)+1 if change=="mixers" else True
        events.append({"actor":state["id"],"trigger":component,"mutation":change,
                       "before_priority":a["priority"]})
    return events


def run(model_dir,out,rounds=3):
    out=Path(out)
    if out.exists(): raise ValueError("Use a new adversarial output directory")
    states=[{"id":f"actor-{n}","label":int(n<8),"family":FAMILIES[n%4]} for n in range(16)]
    report={"scope":"Seed-assisted synthetic actor-level stress test; not held-out operational performance",
            "rounds":[],"mutations":[],"truth":json.loads(json.dumps(states))}
    for i in range(rounds):
        result=round_run(model_dir,out,states,i);report["rounds"].append(result)
        if i<rounds-1: report["mutations"].append(mutate(states,result))
    report["limitations"]=["Mutations are chosen only for flagged positive actors.",
        "All misses and unchanged/increased scores are retained.",
        "Seed-origin transactions are excluded from actor detection scores.",
        "Fixtures model metadata and declared values, not consensus-valid Bitcoin UTXOs."]
    (out/"report.json").write_text(json.dumps(report,indent=2))
    return report


def attempt(data):
    """Advance one separate simulation round. Never rewrite the investigator's case."""
    data=Path(data);out=data/"live-evasion";statefile=out/"state.json"
    if statefile.exists(): state=json.loads(statefile.read_text())
    else: state={"actors":[{"id":f"actor-{n}","label":int(n<4),"family":FAMILIES[n%4]} for n in range(8)],"round":0}
    if state["round"]>=12: raise ValueError("Live simulation reached its 12-round limit; create a fresh demo")
    if state["round"]==0:
        baseline=round_run(data/"model",out,state["actors"],0)
        state["previous"]=baseline;state["round"]=1
    events=mutate(state["actors"],state["previous"])
    after=round_run(data/"model",out,state["actors"],state["round"])
    result={"before":state["previous"],"after":after,"mutations":events,
            "scope":"Separate synthetic sandbox; changes are measured, not guaranteed to lower the score"}
    state.update(previous=after,round=state["round"]+1)
    statefile.write_text(json.dumps(state,indent=2))
    (out/"latest-result.json").write_text(json.dumps(result,indent=2))
    return result
