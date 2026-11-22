"""Snowflake backend for the runner: same interface as LocalStore, key-pair authentication.

Environment: PVSWEEP_SNOWFLAKE_ACCOUNT, PVSWEEP_SNOWFLAKE_USER (default PVSWEEP_RUNNER),
PVSWEEP_SNOWFLAKE_PRIVATE_KEY (PEM text) or PVSWEEP_SNOWFLAKE_PRIVATE_KEY_PATH, optional
PVSWEEP_SNOWFLAKE_DATABASE (default PVSWEEP; CI points it at a clone).

Not exercised yet: there is no Snowflake account at the time of writing (docs/ops/snowflake-setup.md).
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from pathlib import Path


def connect(role: str = "PVSWEEP_PIPELINE", user_env: str = "PVSWEEP_SNOWFLAKE_USER", default_user: str = "PVSWEEP_RUNNER"):
    import snowflake.connector
    from cryptography.hazmat.primitives import serialization

    key_pem = os.environ.get("PVSWEEP_SNOWFLAKE_PRIVATE_KEY") or Path(os.environ["PVSWEEP_SNOWFLAKE_PRIVATE_KEY_PATH"]).read_text()
    key = serialization.load_pem_private_key(key_pem.encode(), password=None)
    der = key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    return snowflake.connector.connect(
        account=os.environ["PVSWEEP_SNOWFLAKE_ACCOUNT"], user=os.environ.get(user_env, default_user), private_key=der,
        role=role, warehouse="PVSWEEP_WH", database=os.environ.get("PVSWEEP_SNOWFLAKE_DATABASE", "PVSWEEP"),
        paramstyle="qmark",
    )


class SnowflakeStore:
    def __init__(self):
        self.con = connect()
        self.lock = threading.RLock()

    def _exec(self, sql: str, params=None):
        with self.lock:
            cur = self.con.cursor()
            try:
                cur.execute(sql, params or [])
                return cur
            except Exception:
                cur.close()
                raise

    def query(self, sql: str, params=None):
        cur = self._exec(sql, params)
        try:
            return cur.fetchall()
        finally:
            cur.close()

    def records(self, channels, limit, record_ids):
        sql = ("SELECT record_id, channel_code, channel_received_date, country, vendor_code, vendor_reference, record_text "
               "FROM SRC.SOURCE_RECORD")
        params, where = [], []
        if channels:
            where.append(f"channel_code IN ({','.join('?' * len(channels))})")
            params += channels
        if record_ids:
            where.append(f"record_id IN ({','.join('?' * len(record_ids))})")
            params += record_ids
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY record_id"
        if limit:
            sql += f" LIMIT {int(limit)}"
        cols = ["record_id", "channel_code", "channel_received_date", "country", "vendor_code", "vendor_reference", "record_text"]
        return [dict(zip(cols, r, strict=True)) for r in self.query(sql, params)]

    def vocab(self) -> set[str]:
        return {r[0].strip().lower() for r in self.query("SELECT pt_name FROM REF.PT_VOCAB")}

    def channel_meta(self) -> dict:
        rows = self.query("SELECT c.channel_code, c.report_type, c.vendor_code, v.forwarding_business_days "
                          "FROM REF.CHANNEL c LEFT JOIN REF.VENDOR v USING (vendor_code)")
        return {r[0]: (r[1], r[2], r[3]) for r in rows}

    def ime_terms(self) -> set[str]:
        return {r[0].lower() for r in self.query("SELECT pt_name FROM REF.IME_TERM")}

    def start_run(self, provider, prompt_version, code_version, scope) -> str:
        run_id = f"run-{uuid.uuid4().hex[:12]}"
        self._exec("INSERT INTO SWEEP.RUN (run_id, provider, prompt_version, code_version, scope, status) "
                   "SELECT ?, ?, ?, ?, PARSE_JSON(?), 'running'", [run_id, provider, prompt_version, code_version, json.dumps(scope)]).close()
        return run_id

    def finish_run(self, run_id, counts, cost_usd, status):
        self._exec("UPDATE SWEEP.RUN SET finished_at = CURRENT_TIMESTAMP(), counts = PARSE_JSON(?), cost_usd = ?, status = ? WHERE run_id = ?",
                   [json.dumps(counts), cost_usd, status, run_id]).close()

    def insert_screening(self, run_id, record_id, cls, criteria, evidence, confidence, result):
        self._exec("INSERT INTO SWEEP.SCREENING (run_id, record_id, screening_class, criteria_patient, criteria_reporter, "
                   "criteria_product, criteria_event, evidence, confidence, result) "
                   "SELECT ?, ?, ?, ?, ?, ?, ?, PARSE_JSON(?), ?, PARSE_JSON(?)",
                   [run_id, record_id, cls, criteria.get("identifiable_patient"), criteria.get("identifiable_reporter"),
                    criteria.get("suspect_product"), criteria.get("event"), json.dumps(evidence), confidence, json.dumps(result)]).close()

    def insert_extraction(self, run_id, record_id, result, valid, problems, tier):
        self._exec("INSERT INTO SWEEP.EXTRACTION (run_id, record_id, result, valid, problems, model_tier) "
                   "SELECT ?, ?, PARSE_JSON(?), ?, PARSE_JSON(?), ?",
                   [run_id, record_id, json.dumps(result), valid, json.dumps(problems), tier]).close()

    def insert_rule_result(self, run_id, record_id, r: dict):
        cols = ["ownership", "substance", "report_type", "causality_required", "ime_flag", "serious", "criteria_complete",
                "proposed_day0", "regulatory_deadline", "days_remaining", "regulatory_status", "forwarding_days", "forwarding_status"]
        self._exec(f"INSERT INTO SWEEP.RULE_RESULT (run_id, record_id, {', '.join(cols)}) VALUES (?, ?, {', '.join('?' * len(cols))})",
                   [run_id, record_id, *[r[c] for c in cols]]).close()

    def insert_candidates(self, run_id, record_id, cands):
        for c in cands:
            self._exec("INSERT INTO SWEEP.MATCH_CANDIDATE (run_id, record_id, source, candidate_id, blocking_keys) "
                       "SELECT ?, ?, ?, ?, PARSE_JSON(?)", [run_id, record_id, c["source"], c["candidate_id"], json.dumps(c["keys"])]).close()

    def insert_match_decision(self, run_id, record_id, d: dict):
        self._exec("INSERT INTO SWEEP.MATCH_DECISION (run_id, record_id, outcome, matched_ids, new_facts, justification, confidence, "
                   "tool_calls, agent_name, agent_version, valid) "
                   "SELECT ?, ?, ?, PARSE_JSON(?), PARSE_JSON(?), ?, ?, PARSE_JSON(?), ?, ?, ?",
                   [run_id, record_id, d["outcome"], json.dumps(d.get("matched_ids", [])), json.dumps(d.get("new_facts", [])),
                    d.get("justification"), d.get("confidence"), json.dumps(d.get("tool_calls", []), default=str), d.get("agent_name"),
                    d.get("agent_version"), d.get("valid", True)]).close()

    def insert_model_call(self, row: dict):
        cols = ["call_id", "run_id", "record_id", "step", "provider", "deployment", "agent_name", "agent_version", "prompt_version",
                "schema_version", "effort", "input_hash", "output_hash", "input_tokens", "output_tokens", "cached_tokens",
                "latency_ms", "status", "error"]
        self._exec(f"INSERT INTO AUDIT.MODEL_CALL ({', '.join(cols)}, raw_output) SELECT {', '.join('?' * len(cols))}, PARSE_JSON(?)",
                   [*[row.get(c) for c in cols], row.get("raw_output") or "null"]).close()
