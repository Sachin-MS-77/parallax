"""Small evidence-justifying subgraphs, plus deterministic local vector rendering."""
import json
import networkx as nx
from reportlab.graphics.shapes import Drawing, Circle, Line, String
from reportlab.lib.colors import HexColor


def minimal_graph(db, alerts):
    selected = {a["address"] for a in alerts}
    txids = set()
    for a in alerts:
        supporting=set()
        for rule in a["rules"]: supporting.update(rule.get("txids",[]))
        for change in a.get("behavioral_drift",{}).get("changes",[]):
            supporting.update(change.get("before_txids",[]))
            supporting.update(change.get("after_txids",[]))
            supporting.add(change["txid"])
        for path in a.get("taint",{}).get("sources",[]): supporting.update(path["txids"])
        if not supporting: supporting.update(a["txids"][:1])
        txids.update(supporting)
    nodes, edges = {}, []
    def node(i,kind,label): nodes[i]={"id":i,"kind":kind,"label":label,"selected":label in selected}
    for txid in sorted(txids):
        if not db.execute("SELECT 1 FROM transactions WHERE txid=?",(txid,)).fetchone(): continue
        node("tx:"+txid,"transaction",txid)
        for f in db.execute("SELECT * FROM flows WHERE txid=?",(txid,)):
            aid="address:"+f["address"]; node(aid,"address",f["address"])
            source,target=(aid,"tx:"+txid) if f["direction"]=="input" else ("tx:"+txid,aid)
            edges.append({"source":source,"target":target,"kind":f["direction"],"amount_sats":f["amount_sats"]})
        observation=db.execute("SELECT * FROM observations WHERE txid=? AND src_ip IS NOT NULL ORDER BY timestamp,id LIMIT 1",(txid,)).fetchone()
        if observation:
            iid="ip:"+observation["src_ip"];node(iid,"ip",observation["src_ip"])
            edges.append({"source":iid,"target":"tx:"+txid,"kind":"first_observed_relay",
                          "observation_id":observation["id"],"ownership_claim":False})
    return {"nodes":list(nodes.values()),"edges":edges,"txids":sorted(txids),
            "scope":"Union of supporting rule/change/taint paths; minimal by evidence selection, not a mathematically minimum graph"}


def drawing(data, width=510,height=250):
    nodes=data["nodes"][:80]; ids={n["id"] for n in nodes}
    graph=nx.Graph()
    graph.add_nodes_from(ids)
    graph.add_edges_from((e["source"],e["target"]) for e in data["edges"] if e["source"] in ids and e["target"] in ids)
    pos=nx.spring_layout(graph,seed=41,iterations=60) if ids else {}
    canvas=Drawing(width,height)
    colors={"address":"#7649a5","transaction":"#277fa1","ip":"#ba7e32","wallet":"#927933"}
    coords={n:(20+(float(x)+1)*(width-40)/2,25+(float(y)+1)*(height-50)/2) for n,(x,y) in pos.items()}
    for a,b in graph.edges:
        x,y=coords[a];xx,yy=coords[b];canvas.add(Line(x,y,xx,yy,strokeColor=HexColor("#c5bfd0"),strokeWidth=.5))
    for i,n in enumerate(nodes):
        x,y=coords[n["id"]];canvas.add(Circle(x,y,4,fillColor=HexColor(colors[n["kind"]]),strokeColor=None))
        if n.get("selected") or n["kind"]=="ip":
            canvas.add(String(x+5,y+5,n["label"][:16],fontSize=5,fillColor=HexColor("#30293a")))
    if len(data["nodes"])>80:
        canvas.add(String(0,0,f"Figure limited to 80/{len(data['nodes'])} nodes. Full graph is in signed case.json.",fontSize=7))
    return canvas
