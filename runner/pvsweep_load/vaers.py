"""VAERS benchmark samples: coding (narrative with coded symptoms) and seriousness (outcome labels).

Samples are deterministic: rows are ordered by a hash of their content and the first N are taken,
so every load produces the same benchmark for the pinned revisions.
"""

from __future__ import annotations

import duckdb

from .cache import fetch
from .sources import VAERS_NARRATIVES, VAERS_OUTCOMES


def build(con: duckdb.DuckDBPyConnection, sample_size: int, cache_dir) -> list[dict]:
    narratives = fetch(VAERS_NARRATIVES, "data.parquet", cache_dir).as_posix()
    con.execute(f"""
    CREATE OR REPLACE TABLE vaers_coding AS
    WITH src AS (
        SELECT input, output AS narrative,
               -- fields are separated by " | " or by newlines depending on the row
               regexp_extract(input, 'Age: ([^|\n]*)', 1) AS age_raw,
               regexp_extract(input, 'Sex: ([^|\n]*)', 1) AS sex_raw,
               regexp_extract(input, 'Vaccine: ([^|\n]*)', 1) AS vaccine_raw,
               regexp_extract(input, 'Symptoms: ([^\n]*)', 1) AS symptoms_raw
        FROM read_parquet('{narratives}')
        WHERE length(output) BETWEEN 80 AND 2000
    )
    SELECT 'VAERS-C-' || row_number() OVER (ORDER BY hash(input || narrative)) AS benchmark_id,
           try_cast(trim(age_raw) AS DOUBLE)   AS age_years,
           CASE trim(sex_raw) WHEN 'F' THEN 'female' WHEN 'M' THEN 'male' ELSE 'unknown' END AS sex,
           trim(vaccine_raw)                   AS vaccine,
           list_transform(string_split(symptoms_raw, ','), lambda x: trim(x)) AS symptom_pts,
           narrative
    FROM src
    ORDER BY hash(input || narrative)
    LIMIT {sample_size}""")

    outcomes = ", ".join(f"'{fetch(VAERS_OUTCOMES, p, cache_dir).as_posix()}'" for p in (
        "data/train-00000-of-00002.parquet", "data/train-00001-of-00002.parquet"))
    con.execute(f"""
    CREATE OR REPLACE TABLE vaers_outcomes AS
    WITH src AS (
        SELECT id, text, label FROM read_parquet([{outcomes}])
        WHERE length(text) BETWEEN 80 AND 2000
    ),
    ranked AS (
        SELECT *, row_number() OVER (PARTITION BY label ORDER BY hash(id::VARCHAR || text)) AS rn FROM src
    )
    SELECT 'VAERS-O-' || id AS benchmark_id, text AS narrative,
           -- ClassLabel order from the dataset card
           CASE label WHEN 0 THEN 'No event' WHEN 1 THEN 'ER_VISIT' WHEN 2 THEN 'ER_VISIT, HOSPITAL' WHEN 3 THEN 'DIED'
                      WHEN 4 THEN 'HOSPITAL' WHEN 5 THEN 'ER_VISIT, HOSPITAL, DIED' WHEN 6 THEN 'HOSPITAL, DIED'
                      WHEN 7 THEN 'ER_VISIT, DIED' END AS outcome_label,
           label IN (2, 4, 5, 6)      AS hospitalisation,
           label IN (3, 5, 6, 7)      AS death
    FROM ranked
    WHERE rn <= {max(1, sample_size // 8)}""")

    return [
        {"source": VAERS_NARRATIVES, "rows": {"vaers_coding": con.execute("SELECT count(*) FROM vaers_coding").fetchone()[0]}},
        {"source": VAERS_OUTCOMES, "rows": {"vaers_outcomes": con.execute("SELECT count(*) FROM vaers_outcomes").fetchone()[0]}},
    ]
