"""Bounded Polars batches with DuckDB staging; no extensions or remote storage."""
import json
from itertools import islice
import duckdb
import polars as pl
from .storage import canonical


def staged_records(iterator, batch_size=2048):
    """Keep row ordering/provenance stable across CSV, XML and JSON adapters."""
    iterator = iter(iterator)
    db = duckdb.connect(":memory:")
    db.execute("SET enable_external_access=false")
    db.execute("CREATE TABLE batch (ordinal BIGINT, raw VARCHAR)")
    ordinal = 0
    try:
        while True:
            items = list(islice(iterator, batch_size))
            if not items: break
            frame = pl.DataFrame({"ordinal":range(ordinal+1,ordinal+len(items)+1),
                                  "raw":[canonical(item) for item in items]})
            db.executemany("INSERT INTO batch VALUES (?,?)", frame.iter_rows())
            for number, body in db.execute("SELECT ordinal,raw FROM batch ORDER BY ordinal").fetchall():
                yield number, json.loads(body)
            ordinal += len(items)
            db.execute("DELETE FROM batch")
    finally:
        db.close()
