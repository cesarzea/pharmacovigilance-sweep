"""Read-only data access for the agent's tools: DuckDB locally, Snowflake in the hosted agent.

Every tool runs a fixed, parameterised query over the AGENT_API views. The model never writes SQL.
"""

from __future__ import annotations

import os
from pathlib import Path

LOCAL_VIEWS = """
CREATE SCHEMA IF NOT EXISTS AGENT_API;
CREATE OR REPLACE VIEW AGENT_API.SAFETY_CASE_SUMMARY AS
SELECT c.case_id, c.initial_receipt_date, c.latest_receipt_date, c.event_date, c.case_version, c.reporter_type,
       c.age_years, c.sex, c.occurrence_country, c.serious, c.hospitalisation, c.death, d.substances, d.products, e.events
FROM PV.SAFETY_CASE c
LEFT JOIN (SELECT case_id, list(DISTINCT substance ORDER BY substance) AS substances,
                  list(DISTINCT product_name ORDER BY product_name) AS products
           FROM PV.CASE_DRUG WHERE role IN ('primary_suspect','secondary_suspect') GROUP BY case_id) d USING (case_id)
LEFT JOIN (SELECT case_id, list(DISTINCT pt ORDER BY pt) AS events FROM PV.CASE_EVENT GROUP BY case_id) e USING (case_id);
CREATE OR REPLACE VIEW AGENT_API.CASE_HISTORY AS SELECT * FROM PV.CASE_VERSION;
CREATE OR REPLACE VIEW AGENT_API.INTAKE_QUEUE AS SELECT * FROM PV.INTAKE_QUEUE;
CREATE OR REPLACE VIEW AGENT_API.INTAKE_LOG AS SELECT * FROM PV.INTAKE_LOG;
CREATE OR REPLACE VIEW AGENT_API.VENDOR_TX_LOG AS SELECT * FROM PV.VENDOR_TX_LOG;
"""


class Backend:
    dialect = "duckdb"

    def rows(self, sql: str, params: list) -> list[dict]:
        raise NotImplementedError


class DuckDBBackend(Backend):
    """Shares the runner's local database. The framework runs sync tools in worker threads, so each
    query gets its own cursor and the view setup is serialised."""

    def __init__(self, con):
        import threading

        self._root = con
        self._lock = threading.Lock()
        with self._lock:
            con.cursor().execute(LOCAL_VIEWS)

    def rows(self, sql, params):
        with self._lock:
            cur = self._root.cursor()
            try:
                cur.execute(sql, params)
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
            finally:
                cur.close()


class SnowflakeBackend(Backend):
    """Key-pair authentication as PVSWEEP_AGENT; the key arrives through a Foundry connection."""

    dialect = "snowflake"

    def __init__(self):
        import snowflake.connector
        from cryptography.hazmat.primitives import serialization

        key_pem = os.environ.get("PVSWEEP_SNOWFLAKE_PRIVATE_KEY") or Path(os.environ["PVSWEEP_SNOWFLAKE_PRIVATE_KEY_PATH"]).read_text()
        key = serialization.load_pem_private_key(key_pem.encode(), password=None)
        der = key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        self.con = snowflake.connector.connect(
            account=os.environ["PVSWEEP_SNOWFLAKE_ACCOUNT"], user=os.environ.get("PVSWEEP_SNOWFLAKE_USER", "PVSWEEP_AGENT"),
            private_key=der, role="PVSWEEP_AGENT", warehouse="PVSWEEP_WH",
            database=os.environ.get("PVSWEEP_SNOWFLAKE_DATABASE", "PVSWEEP"), schema="AGENT_API",
        )

    def rows(self, sql, params):
        # Snowflake uses %s placeholders with the default paramstyle; the tools write '?'.
        cur = self.con.cursor()
        cur.execute(sql.replace("?", "%s"), params)
        cols = [d[0].lower() for d in cur.description]
        return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


def from_env(local_con=None) -> Backend:
    if local_con is not None:
        return DuckDBBackend(local_con)
    return SnowflakeBackend()
