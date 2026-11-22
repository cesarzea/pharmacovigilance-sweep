"""Demo-mode term vocabulary: Preferred Term names seen in the public datasets.

Not MedDRA. It only lets the pipeline check that a proposed term exists somewhere in real coded
data. Production mode loads a licensed MedDRA release instead (docs/poc-definition.md, section 8).
"""

from __future__ import annotations

import duckdb

from .cache import fetch
from .sources import FAERS


def build(con: duckdb.DuckDBPyConnection, cache_dir) -> dict:
    reac = fetch(FAERS, "data/REAC.parquet", cache_dir).as_posix()
    con.execute(f"""
    CREATE OR REPLACE TABLE pt_vocab AS
    SELECT pt_name, sum(n) AS occurrences FROM (
        SELECT trim(pt) AS pt_name, count(*) AS n FROM read_parquet('{reac}') WHERE pt IS NOT NULL GROUP BY 1
        UNION ALL
        SELECT s AS pt_name, count(*) AS n FROM vaers_coding, unnest(symptom_pts) AS t(s) WHERE s <> '' GROUP BY 1
    ) GROUP BY 1""")
    return {"rows": {"pt_vocab": con.execute("SELECT count(*) FROM pt_vocab").fetchone()[0]}}
