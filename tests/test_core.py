import json
from pathlib import Path

import pytest

from parallax.ingest import normalize
from parallax.synthetic import generate


TX = "a" * 64


def record(**overrides):
    value = {
        "timestamp": "2025-01-01T00:00:00+00:00",
        "src_ip": "198.51.100.10",
        "dst_ip": "203.0.113.10",
        "src_port": 20000,
        "dst_port": 8333,
        "txid": TX,
        "input_addresses": ["wallet-a"],
        "output_addresses": ["wallet-b"],
        "input_amounts": ["1.00000000"],
        "output_amounts": ["0.99999000"],
        "fee": "0.00001000",
    }
    value.update(overrides)
    return value


def test_normalize_uses_satoshis_and_preserves_observation_limits():
    row = normalize(record())
    assert row["input_sats"] == [100_000_000]
    assert row["output_sats"] == [99_999_000]
    assert row["fee_sats"] == 1_000
    assert row["geo_source"] == "unavailable"


@pytest.mark.parametrize(
    "field,value",
    [("txid", "bad"), ("src_ip", "not-an-ip"), ("src_port", 70000),
     ("input_amounts", ["1.000000001"]), ("output_addresses", [])],
)
def test_normalize_rejects_invalid_records(field, value):
    with pytest.raises(ValueError):
        normalize(record(**{field: value}))


def test_synthetic_labels_are_separate_from_metadata(tmp_path):
    result = generate(tmp_path, split="test", entities=8)
    metadata = Path(result["metadata"]).read_text().splitlines()
    assert metadata
    assert "label" not in json.loads(metadata[0])
    labels = json.loads((tmp_path / "test-labels.json").read_text())
    assert labels["domain"] == "synthetic"
    assert set(labels["labels"])
