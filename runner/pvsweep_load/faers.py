"""FAERS extract: the fictional MAH's safety database.

Keeps EU/EEA reports where one of the portfolio substances is a primary or secondary suspect,
remaps those products to Contoso's fictional brands, and shifts every full date by a fixed offset
so the extract looks current. Only the latest version of each case exists in FAERS.
"""

from __future__ import annotations

import duckdb

from .cache import fetch
from .sources import EU_EEA, FAERS, PORTFOLIO


def _sql_list(values) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


def _substance_case() -> str:
    whens = "\n".join(
        f"      WHEN upper(prod_ai) IN {_sql_list(aliases)} THEN '{substance}'"
        for substance, aliases in PORTFOLIO.items()
    )
    return f"CASE\n{whens}\n      ELSE NULL END"


def build(con: duckdb.DuckDBPyConnection, reference_date: str, brands: dict[str, str], cache_dir) -> dict:
    """Create the FAERS-derived tables in `con` and return the manifest entry."""
    demo, drug, reac, outc, ther, indi = (fetch(FAERS, f"data/{t}.parquet", cache_dir).as_posix() for t in
                                          ("DEMO", "DRUG", "REAC", "OUTC", "THER", "INDI"))
    brand_case = "CASE\n" + "\n".join(
        f"      WHEN substance = '{s}' THEN '{b}'" for s, b in brands.items()) + "\n      ELSE NULL END"

    con.execute(f"""
    CREATE OR REPLACE TABLE eu_demo AS
    SELECT * FROM read_parquet('{demo}') WHERE occr_country IN {_sql_list(EU_EEA)}""")

    con.execute(f"""
    CREATE OR REPLACE TABLE eu_drug AS
    SELECT g.*, {_substance_case()} AS substance
    FROM read_parquet('{drug}') g
    WHERE g.primaryid IN (SELECT primaryid FROM eu_demo)""")

    con.execute("""
    CREATE OR REPLACE TABLE scope AS
    SELECT DISTINCT primaryid FROM eu_drug WHERE substance IS NOT NULL AND role_cod IN ('PS', 'SS')""")

    # Fixed date offset: the newest receipt date in scope lands on the reference date.
    offset_days = con.execute(f"""
    SELECT date_diff('day', max(try_strptime(fda_dt, '%Y%m%d'))::DATE, DATE '{reference_date}')
    FROM eu_demo WHERE primaryid IN (SELECT primaryid FROM scope)""").fetchone()[0]

    def shifted(col: str) -> str:
        return f"CASE WHEN length({col}) = 8 THEN try_strptime({col}, '%Y%m%d')::DATE + INTERVAL {offset_days} DAY END::DATE"

    con.execute(f"""
    CREATE OR REPLACE TABLE safety_case AS
    SELECT 'CONTOSO-' || d.caseid                         AS case_id,
           d.caseid                                        AS source_case_id,
           -- FAERS has no patient initials; safety databases do. Deterministic synthetic initials let the
           -- matching step use the identifier a real database would offer.
           chr(65 + (hash(d.caseid) % 26)::INTEGER) || chr(65 + ((hash(d.caseid) // 26) % 26)::INTEGER) AS patient_initials,
           d.caseversion::INTEGER                          AS case_version,
           {shifted('d.init_fda_dt')}                      AS initial_receipt_date,
           {shifted('d.fda_dt')}                           AS latest_receipt_date,
           {shifted('d.event_dt')}                         AS event_date,
           CASE d.rept_cod WHEN 'EXP' THEN 'expedited' WHEN 'PER' THEN 'periodic' WHEN 'DIR' THEN 'direct' ELSE lower(d.rept_cod) END AS report_kind,
           CASE d.occp_cod WHEN 'MD' THEN 'physician' WHEN 'PH' THEN 'pharmacist' WHEN 'HP' THEN 'other_hcp'
                           WHEN 'CN' THEN 'consumer' WHEN 'LW' THEN 'lawyer' ELSE 'unknown' END AS reporter_type,
           CASE d.age_cod WHEN 'YR' THEN d.age::DOUBLE WHEN 'MON' THEN d.age::DOUBLE / 12 WHEN 'WK' THEN d.age::DOUBLE / 52
                          WHEN 'DY' THEN d.age::DOUBLE / 365 WHEN 'DEC' THEN d.age::DOUBLE * 10 END AS age_years,
           CASE d.sex WHEN 'F' THEN 'female' WHEN 'M' THEN 'male' ELSE 'unknown' END AS sex,
           d.occr_country                                  AS occurrence_country,
           d.reporter_country                              AS reporter_country,
           o.serious, o.death, o.life_threatening, o.hospitalisation, o.disability, o.congenital_anomaly, o.other_medically_important
    FROM eu_demo d
    JOIN scope s USING (primaryid)
    LEFT JOIN (
        SELECT primaryid,
               bool_or(outc_cod IN ('DE','LT','HO','DS','CA','RI','OT')) AS serious,
               bool_or(outc_cod = 'DE') AS death, bool_or(outc_cod = 'LT') AS life_threatening,
               bool_or(outc_cod = 'HO') AS hospitalisation, bool_or(outc_cod = 'DS') AS disability,
               bool_or(outc_cod = 'CA') AS congenital_anomaly, bool_or(outc_cod IN ('RI','OT')) AS other_medically_important
        FROM read_parquet('{outc}') GROUP BY primaryid
    ) o USING (primaryid)""")

    con.execute(f"""
    CREATE OR REPLACE TABLE case_drug AS
    SELECT 'CONTOSO-' || g.caseid                          AS case_id,
           g.drug_seq::INTEGER                             AS drug_seq,
           CASE g.role_cod WHEN 'PS' THEN 'primary_suspect' WHEN 'SS' THEN 'secondary_suspect'
                           WHEN 'C' THEN 'concomitant' WHEN 'I' THEN 'interacting' END AS role,
           g.substance,
           CASE WHEN g.substance IS NOT NULL THEN {brand_case.replace('substance', 'g.substance')}
                ELSE g.drugname END                        AS product_name,
           CASE WHEN g.substance IS NOT NULL THEN 'own_brand' ELSE 'other' END AS ownership,
           g.prod_ai                                       AS active_ingredient,
           g.route, g.dose_vbm AS dose_verbatim, g.lot_num,
           t.start_date, t.end_date
    FROM eu_drug g
    JOIN scope s USING (primaryid)
    LEFT JOIN (
        SELECT primaryid, dsg_drug_seq, min({shifted('start_dt')}) AS start_date, max({shifted('end_dt')}) AS end_date
        FROM read_parquet('{ther}') GROUP BY 1, 2
    ) t ON t.primaryid = g.primaryid AND t.dsg_drug_seq = g.drug_seq""")

    con.execute(f"""
    CREATE OR REPLACE TABLE case_event AS
    SELECT 'CONTOSO-' || r.caseid AS case_id, r.pt AS pt,
           CASE r.drug_rec_act WHEN 'PT' THEN 'positive' WHEN 'NT' THEN 'negative' END AS dechallenge_recovery
    FROM read_parquet('{reac}') r JOIN scope s USING (primaryid)""")

    con.execute(f"""
    CREATE OR REPLACE TABLE case_indication AS
    SELECT 'CONTOSO-' || i.caseid AS case_id, i.indi_drug_seq::INTEGER AS drug_seq, i.indi_pt AS indication_pt
    FROM read_parquet('{indi}') i JOIN scope s USING (primaryid)""")

    counts = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
              for t in ("safety_case", "case_drug", "case_event", "case_indication")}
    return {"source": FAERS, "date_offset_days": int(offset_days), "rows": counts}
