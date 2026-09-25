"""Collect measured synthetic evidence without copying private signing keys."""
import argparse
import importlib.util
import json
import shutil
import sys
import zipfile
from pathlib import Path

from parallax.evidence import dossier, keypair
from parallax.model import score
from parallax.storage import connect, canonical

p=argparse.ArgumentParser()
p.add_argument("--demo",required=True);p.add_argument("--stress",required=True);p.add_argument("--out",required=True)
args=p.parse_args()
demo,stress,out=map(Path,(args.demo,args.stress,args.out))
out.mkdir(parents=True,exist_ok=False)
score(stress/"round-0.sqlite",demo/"model")
db=connect(stress/"round-0.sqlite")
address="sim_actor-1_wallet"
archive=dossier(db,address,stress/"keys")
(out/"sample-case.zip").write_bytes(archive)
with (out/"original-audit.jsonl").open("w") as f:
    for row in db.execute("SELECT * FROM audit ORDER BY seq"):f.write(canonical(dict(row))+"\n")
db.close()
_,public=keypair(stress/"keys")
(out/"signer-public-key.txt").write_text(public.hex()+"\n")
with zipfile.ZipFile(out/"sample-case.zip") as z:
    for name in ("report.pdf","report.pdf.sig","subgraph.svg"):
        (out/name).write_bytes(z.read(name))
for source,name in ((demo/"evaluation.json","evaluation.json"),
                    (demo/"benchmark.json","benchmark.json"),
                    (stress/"report.json","adversarial-report.json")):
    shutil.copyfile(source,out/name)
verifier=Path(__file__).with_name("verify_dossier_standalone.py")
shutil.copyfile(verifier,out/verifier.name)
spec=importlib.util.spec_from_file_location("independent_verifier",verifier)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
result=module.verify(out/"sample-case.zip",out/"original-audit.jsonl",out/"signer-public-key.txt")
(out/"verification.json").write_text(json.dumps(result,indent=2))
print(json.dumps({"output":str(out),"verification":result},indent=2))
