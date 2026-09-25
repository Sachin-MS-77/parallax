"""Audited analyst feedback updates the five configured weights and re-ranks."""
import math
from pathlib import Path
from datetime import datetime, timezone
from .analysis import config
from .evidence import get_alert
from .storage import connect, canonical, audit, set_meta, get_meta


def review_case(data, address, status, reason, false_positive=False):
    if status not in ("New","Triaging","Escalated","Dismissed") or len(reason.strip())<5:
        raise ValueError("A valid state and meaningful reason are required")
    if false_positive and status != "Dismissed":
        raise ValueError("Confirmed false positives must be dismissed")
    data = Path(data); db = connect(data/"case.sqlite")
    try:
        alert = get_alert(db,address)
        settings = config(db)
        previous = get_meta(db,"feedback_addresses",[])
        changed = False
        with db:
            stamp = datetime.now(timezone.utc).isoformat()
            db.execute("INSERT INTO reviews(address,status,reason,timestamp) VALUES (?,?,?,?)",
                       (address,status,reason.strip(),stamp))
            audit(db,{"event":"analyst_review","address":address,"status":status,"reason":reason.strip(),
                      "false_positive":false_positive,"timestamp":stamp})
            before = settings["weights"].copy()
            if false_positive and address not in previous:
                # Decrease weights most responsible for this explicit false-positive decision.
                # Bounded multiplicative update; renormalize; this is not statistical calibration.
                weights = {k:max(.01,w*math.exp(-settings["feedback_rate"]*(alert["subscores"][k]["value"] or 0)))
                           for k,w in before.items()}
                total = sum(weights.values())
                settings = {**settings,"version":settings["version"]+1,
                            "weights":{k:v/total for k,v in weights.items()}}
                set_meta(db,"fracture_config",settings)
                set_meta(db,"feedback_addresses",previous+[address])
                set_meta(db,"evaluation",None)
                set_meta(db,"scored",False)
                audit(db,{"event":"fracture_weight_update","address":address,"before":before,
                          "after":settings["weights"],"version":settings["version"],
                          "scope":"Analyst heuristic update; independent re-evaluation required"})
                changed = True
    finally:
        db.close()
    if changed:
        (data/"fracture-config.json").write_text(canonical(settings)+"\n")
        from .model import score
        score(data/"case.sqlite",data/"model")
    return {"saved":True,"weights_changed":changed,"weights_before":before,
            "weights_after":settings["weights"],"version":settings["version"],
            "note":"Repeated dismissal of the same address does not repeatedly train the weights"}
