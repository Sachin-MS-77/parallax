#!/usr/bin/env python3
"""Create an auditable, satoshi-consistent copy of the supplied synthetic data.

The supplied generator stores one aggregate input amount for some multi-input
records and has a handful of rounding discrepancies. The original file is
never changed. This adapter distributes aggregate inputs equally, corrects
only sub-satoshi-rounding overflow, recomputes fee, and records every repair.
"""
import argparse, hashlib, json
from decimal import Decimal, ROUND_DOWN
from pathlib import Path

SAT = Decimal("100000000")

def sats(v):
    return int((Decimal(str(v)) * SAT).to_integral_value())

def main():
    p = argparse.ArgumentParser()
    p.add_argument("source", type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--manifest", required=True, type=Path)
    a = p.parse_args()
    raw = a.source.read_bytes()
    rows = json.loads(raw)
    repairs = {"aggregate_input_amounts": 0, "rounding_overflow": 0, "fee_recomputed": 0}
    output = []
    for index, row in enumerate(rows):
        r = dict(row)
        ins = [sats(x) for x in r["input_amounts"]]
        outs = [sats(x) for x in r["output_amounts"]]
        if len(ins) == 1 and len(r["input_addresses"]) > 1:
            total = ins[0]; base, rem = divmod(total, len(r["input_addresses"]))
            ins = [base + (1 if i < rem else 0) for i in range(len(r["input_addresses"]))]
            repairs["aggregate_input_amounts"] += 1
        if sum(outs) > sum(ins) and sum(outs) - sum(ins) <= 4:
            outs[-1] -= sum(outs) - sum(ins)
            repairs["rounding_overflow"] += 1
        if len(ins) != len(r["input_addresses"]) or len(outs) != len(r["output_addresses"]):
            raise ValueError(f"row {index}: unsupported amount/address shape")
        fee = sum(ins) - sum(outs)
        if fee < 0:
            raise ValueError(f"row {index}: outputs exceed inputs beyond rounding")
        r["input_amounts"] = [f"{x / SAT:.8f}" for x in ins]
        r["output_amounts"] = [f"{x / SAT:.8f}" for x in outs]
        r["fee"] = f"{fee / SAT:.8f}"
        if sats(row["fee"]) != fee:
            repairs["fee_recomputed"] += 1
        output.append(r)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(output, indent=2) + "\n")
    manifest = {"source": str(a.source), "source_sha256": hashlib.sha256(raw).hexdigest(),
                "output": str(a.out), "records": len(output), "repairs": repairs,
                "policy": "Original preserved; aggregate inputs split equally; <=4 sat rounding overflow corrected; fee recomputed from satoshi totals"}
    a.manifest.parent.mkdir(parents=True, exist_ok=True)
    a.manifest.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))

if __name__ == "__main__": main()
