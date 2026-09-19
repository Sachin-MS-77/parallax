"""Deterministic scenario fixtures. Labels never appear in ingested metadata."""
import csv
import hashlib
import json
import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, ElementTree

SPLITS = {"train": (41, 0), "calibration": (73, 45), "test": (109, 90)}
BENIGN = ["ordinary", "merchant_batch", "shared_relay", "collaborative_spend", "automated_service"]
POSITIVE = ["rapid_fanout", "relay_burst", "timing_jitter", "amount_fragmentation"]


def btc(sats):
    return f"{Decimal(sats) / Decimal(100_000_000):.8f}"


def generate(directory, split="test", entities=160, seed=None):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    fixed_seed, day = SPLITS[split]
    rng = random.Random(seed if seed is not None else fixed_seed)
    start = datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(days=day)
    rows, labels = [], {}
    for n in range(entities):
        # All IDs are synthetic, disjoint across splits, and never model inputs.
        address = "syn_" + hashlib.sha256(f"{split}:{fixed_seed}:{n}:wallet".encode()).hexdigest()[:32]
        positive = n % 5 == 0
        scenario = POSITIVE[(n // 5) % len(POSITIVE)] if positive else BENIGN[n % len(BENIGN)]
        # Avoid excluding 'ordinary' from mixed splits due to n % 5 assignment.
        if not positive:
            scenario = BENIGN[rng.randrange(len(BENIGN))]
        count = rng.randint(4, 12)
        gap = rng.randint(1800, 20000)
        fanout = rng.randint(1, 3)
        relays = rng.randint(1, 3)
        if scenario == "merchant_batch":
            fanout = rng.randint(8, 16)
        elif scenario == "automated_service":
            gap, count = rng.randint(35, 120), rng.randint(8, 16)
        elif scenario == "collaborative_spend":
            fanout = rng.randint(3, 7)
        elif scenario == "rapid_fanout":
            gap, fanout, count = rng.randint(4, 25), rng.randint(12, 22), rng.randint(15, 24)
        elif scenario == "relay_burst":
            relays = rng.randint(9, 16)
        elif scenario == "timing_jitter":
            gap, fanout, count = rng.randint(100, 600), rng.randint(4, 10), rng.randint(14, 22)
        elif scenario == "amount_fragmentation":
            fanout, count = rng.randint(18, 30), rng.randint(10, 18)
        labels[address] = {"label": int(positive), "scenario": scenario, "entity_id": f"{split}-{n}"}
        elapsed = 0
        for k in range(count):
            elapsed += max(1, int(gap * rng.uniform(0.65, 1.35)))
            when = start + timedelta(seconds=n * 300 + elapsed)
            txid = hashlib.sha256(f"{split}:{fixed_seed}:{n}:{k}".encode()).hexdigest()
            # Metadata scenarios, not spend-valid Bitcoin transactions: no UTXO claims.
            amount = rng.randint(100_000, 30_000_000)
            if scenario == "amount_fragmentation":
                amount = rng.choice([rng.randint(10_000, 60_000), rng.randint(50_000_000, 200_000_000)])
            outputs = [amount // fanout] * fanout
            outputs[-1] += amount - sum(outputs)
            if scenario != "collaborative_spend":
                for j in range(len(outputs) - 1):
                    transfer = rng.randint(0, max(0, outputs[j] // 3))
                    outputs[j] -= transfer
                    outputs[-1] += transfer
            output_addresses = ["syn_" + hashlib.sha256(f"{split}:{n}:{k}:out:{j}".encode()).hexdigest()[:32] for j in range(fanout)]
            fee = rng.randint(300, 2000)
            vsize = rng.randint(140,350)
            for r in range(relays):
                delay = r * (rng.uniform(0.01, 0.15) if scenario == "relay_burst" else rng.uniform(0.5, 3))
                if scenario == "shared_relay":
                    source = f"198.51.100.{1 + r}"
                else:
                    source = f"198.18.{n // 250 % 256}.{1 + (n + r) % 250}"
                rows.append({"timestamp": (when + timedelta(seconds=delay)).isoformat(),
                             "src_ip": source, "dst_ip": f"203.0.113.{1 + r}",
                             "src_port": 20000 + rng.randrange(40000), "dst_port": 8333,
                             "txid": txid, "input_addresses": [address], "output_addresses": output_addresses,
                             "input_amounts": [btc(amount + fee)], "output_amounts": [btc(v) for v in outputs],
                             "fee": btc(fee), "vsize": vsize, "script_type": "p2wpkh", "geo_country": None, "asn": None})
    rows.sort(key=lambda r: (r["timestamp"], r["txid"]))
    metadata = directory / f"{split}.jsonl"
    metadata.write_text("".join(json.dumps(r) + "\n" for r in rows))
    truth = {"domain": "synthetic", "split": split, "seed": seed if seed is not None else fixed_seed,
             "generator_version": "2", "warning": "Designed metadata scenarios, not real attribution or UTXO-valid blockchain data", "labels": labels}
    (directory / f"{split}-labels.json").write_text(json.dumps(truth, indent=2))
    if split == "test":
        sample = rows[:30]
        (directory / "sample.json").write_text(json.dumps({"records": sample}, indent=2))
        with open(directory / "sample.csv", "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(sample[0]))
            writer.writeheader()
            for row in sample:
                writer.writerow({k: json.dumps(v) if isinstance(v, list) else v for k, v in row.items()})
        root = Element("records")
        for row in sample:
            record = SubElement(root, "record")
            for key, value in row.items():
                child = SubElement(record, key)
                if isinstance(value, list):
                    for item in value:
                        SubElement(child, "item").text = str(item)
                elif value is not None:
                    child.text = str(value)
        ElementTree(root).write(directory / "sample.xml", encoding="utf-8", xml_declaration=True)
    return {"metadata": str(metadata), "entities": entities, "observations": len(rows), "positive_entities": sum(x["label"] for x in labels.values())}
