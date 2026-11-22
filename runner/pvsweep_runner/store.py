"""Where records come from and where results go.

LocalStore: a DuckDB file over the staged Parquet and the synthetic JSON, for development and CI
without Snowflake. SnowflakeStore: the real thing, same table names, key-pair authentication.
Both expose the same small interface used by the steps.
"""

from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path

LOCAL_DDL = """
CREATE SCHEMA IF NOT EXISTS SRC; CREATE SCHEMA IF NOT EXISTS SWEEP; CREATE SCHEMA IF NOT EXISTS AUDIT;
CREATE SCHEMA IF NOT EXISTS EVAL; CREATE SCHEMA IF NOT EXISTS PV; CREATE SCHEMA IF NOT EXISTS REF;
CREATE TABLE IF NOT EXISTS SRC.SOURCE_RECORD (record_id VARCHAR PRIMARY KEY, channel_code VARCHAR, channel_received_date DATE,
  country VARCHAR, vendor_code VARCHAR, vendor_reference VARCHAR, record_text VARCHAR, generator VARCHAR);
CREATE TABLE IF NOT EXISTS SWEEP.RUN (run_id VARCHAR PRIMARY KEY, started_at TIMESTAMP, finished_at TIMESTAMP, provider VARCHAR,
  prompt_version VARCHAR, code_version VARCHAR, scope JSON, counts JSON, cost_usd DOUBLE, status VARCHAR);
CREATE TABLE IF NOT EXISTS SWEEP.SCREENING (run_id VARCHAR, record_id VARCHAR, screening_class VARCHAR, criteria_patient BOOLEAN,
  criteria_reporter BOOLEAN, criteria_product BOOLEAN, criteria_event BOOLEAN, evidence JSON, confidence VARCHAR, result JSON,
  created_at TIMESTAMP DEFAULT current_timestamp);
CREATE TABLE IF NOT EXISTS SWEEP.EXTRACTION (run_id VARCHAR, record_id VARCHAR, result JSON, valid BOOLEAN, problems JSON,
  model_tier VARCHAR, created_at TIMESTAMP DEFAULT current_timestamp);
CREATE TABLE IF NOT EXISTS AUDIT.MODEL_CALL (call_id VARCHAR PRIMARY KEY, run_id VARCHAR, record_id VARCHAR, step VARCHAR,
  provider VARCHAR, deployment VARCHAR, agent_name VARCHAR, agent_version VARCHAR, prompt_version VARCHAR, schema_version VARCHAR,
  effort VARCHAR, input_hash VARCHAR, output_hash VARCHAR, raw_output JSON, input_tokens BIGINT, output_tokens BIGINT,
  cached_tokens BIGINT, latency_ms BIGINT, status VARCHAR, error VARCHAR, created_at TIMESTAMP DEFAULT current_timestamp);
CREATE TABLE IF NOT EXISTS PV.INTAKE_QUEUE (intake_id VARCHAR PRIMARY KEY, channel_code VARCHAR, vendor_reference VARCHAR,
  received_by_pv TIMESTAMP, status VARCHAR, case_id VARCHAR, summary VARCHAR);
CREATE TABLE IF NOT EXISTS PV.INTAKE_LOG (intake_id VARCHAR, vendor_code VARCHAR, vendor_reference VARCHAR, received_by_pv TIMESTAMP,
  product_name VARCHAR, event_summary VARCHAR);
CREATE TABLE IF NOT EXISTS PV.VENDOR_TX_LOG (vendor_code VARCHAR, vendor_reference VARCHAR, sent_at TIMESTAMP, product_name VARCHAR,
  event_summary VARCHAR);
CREATE TABLE IF NOT EXISTS PV.CASE_VERSION (case_id VARCHAR, case_version INTEGER, received_date DATE, significant BOOLEAN,
  information_summary VARCHAR);
CREATE TABLE IF NOT EXISTS SWEEP.RULE_RESULT (run_id VARCHAR, record_id VARCHAR, ownership VARCHAR, substance VARCHAR,
  report_type VARCHAR, causality_required BOOLEAN, ime_flag BOOLEAN, serious BOOLEAN, criteria_complete BOOLEAN,
  proposed_day0 DATE, regulatory_deadline DATE, days_remaining INTEGER, regulatory_status VARCHAR, forwarding_days INTEGER,
  forwarding_status VARCHAR, created_at TIMESTAMP DEFAULT current_timestamp);
CREATE TABLE IF NOT EXISTS SWEEP.MATCH_CANDIDATE (run_id VARCHAR, record_id VARCHAR, source VARCHAR, candidate_id VARCHAR,
  blocking_keys JSON);
CREATE TABLE IF NOT EXISTS SWEEP.MATCH_DECISION (run_id VARCHAR, record_id VARCHAR, outcome VARCHAR, matched_ids JSON,
  new_facts JSON, justification VARCHAR, confidence VARCHAR, tool_calls JSON, agent_name VARCHAR, agent_version VARCHAR,
  valid BOOLEAN, created_at TIMESTAMP DEFAULT current_timestamp);
CREATE SCHEMA IF NOT EXISTS REVIEW;
CREATE TABLE IF NOT EXISTS SWEEP.FINDING (run_id VARCHAR, finding_id VARCHAR PRIMARY KEY, record_id VARCHAR, finding_type VARCHAR,
  priority INTEGER, created_at TIMESTAMP DEFAULT current_timestamp);
CREATE TABLE IF NOT EXISTS REVIEW.DECISION (decision_id VARCHAR PRIMARY KEY, finding_id VARCHAR, reviewer VARCHAR,
  decided_at TIMESTAMP DEFAULT current_timestamp, outcome VARCHAR, checklist JSON, confirmed_day0 DATE, rationale VARCHAR,
  supersedes_id VARCHAR);
CREATE TABLE IF NOT EXISTS EVAL.GOLD_RECORD (record_id VARCHAR PRIMARY KEY, kind VARCHAR, timing VARCHAR, gold_screening VARCHAR,
  gold_match VARCHAR, gold_outcome VARCHAR, gold_day0 DATE, substance VARCHAR, product_name VARCHAR, ownership VARCHAR,
  reporter_type VARCHAR, patient_age INTEGER, patient_sex VARCHAR, event_pt VARCHAR, serious BOOLEAN, hospitalisation BOOLEAN,
  causality_statement VARCHAR, special_situation VARCHAR, onset_date DATE, identifiable_patient BOOLEAN,
  identifiable_reporter BOOLEAN, anchor_case_id VARCHAR, anchor_intake_id VARCHAR);
"""

VENDOR_BY_CHANNEL = {"PSP": "PSPV", "MI": "MIV", "SOCIAL": "SOCV"}


class LocalStore:
    def __init__(self, path: str | Path, stage_dir: str | Path, synthetic_dir: str | Path):
        import duckdb

        self.lock = threading.RLock()
        self.con = duckdb.connect(str(path))
        self.con.execute(LOCAL_DDL)
        stage = Path(stage_dir)
        for schema, name in (("PV", "safety_case"), ("PV", "case_drug"), ("PV", "case_event"), ("REF", "pt_vocab")):
            self.con.execute(f"CREATE OR REPLACE VIEW {schema}.{name.upper()} AS SELECT * FROM '{stage / name}.parquet'")
        self._load_synthetic(Path(synthetic_dir))

    def _load_synthetic(self, d: Path):
        plan = json.loads((d / "plan.json").read_text())
        recs = json.loads((d / "source_records.json").read_text()) if (d / "source_records.json").exists() else []
        scen = {s["record_id"]: s for s in plan["scenarios"]}
        self.con.execute("DELETE FROM SRC.SOURCE_RECORD")
        self.con.execute("DELETE FROM EVAL.GOLD_RECORD")
        for r in recs:
            s = scen[r["record_id"]]
            self.con.execute("INSERT INTO SRC.SOURCE_RECORD VALUES (?,?,?,?,?,?,?,?)", [
                r["record_id"], r["channel"], r["channel_received_date"], r["country"],
                VENDOR_BY_CHANNEL.get(r["channel"]), s["extra_facts"].get("vendor_reference"), r["text"], r["generator"]])
        for t in ("INTAKE_QUEUE", "INTAKE_LOG", "VENDOR_TX_LOG", "CASE_VERSION"):
            self.con.execute(f"DELETE FROM PV.{t}")
        for r in plan["intake_queue"]:
            self.con.execute("INSERT INTO PV.INTAKE_QUEUE VALUES (?,?,?,?,?,?,?)",
                             [r["intake_id"], r["channel_code"], r["vendor_reference"], r["received_by_pv"], r["status"],
                              r["case_id"], r["summary"]])
        for r in plan["intake_log"]:
            self.con.execute("INSERT INTO PV.INTAKE_LOG VALUES (?,?,?,?,?,?)",
                             [r["intake_id"], r["vendor_code"], r["vendor_reference"], r["received_by_pv"], r["product_name"],
                              r["event_summary"]])
        for r in plan["vendor_tx_log"]:
            self.con.execute("INSERT INTO PV.VENDOR_TX_LOG VALUES (?,?,?,?,?)",
                             [r["vendor_code"], r["vendor_reference"], r["sent_at"], r["product_name"], r["event_summary"]])
        for r in plan["case_version"]:
            self.con.execute("INSERT INTO PV.CASE_VERSION VALUES (?,?,?,?,?)",
                             [r["case_id"], r["case_version"], r["received_date"], r["significant"], r["information_summary"]])
        for s in plan["scenarios"]:
            self.con.execute("INSERT INTO EVAL.GOLD_RECORD VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
                s["record_id"], s["kind"], s["timing"], s["gold_screening"], s["gold_match"], s["gold_outcome"], s["gold_day0"],
                s["substance"], s["product_name"], s["ownership"], s["reporter_type"], s["patient_age"], s["patient_sex"],
                s["event_pt"], s["serious"], s["hospitalisation"], s["causality_statement"], s["special_situation"],
                s["onset_date"], s["identifiable_patient"], s["identifiable_reporter"], s["anchor_case_id"], s["anchor_intake_id"]])

    # ---- interface -----------------------------------------------------------------------
    def records(self, channels: list[str] | None, limit: int | None, record_ids: list[str] | None) -> list[dict]:
        sql = "SELECT record_id, channel_code, channel_received_date, country, vendor_code, vendor_reference, record_text FROM SRC.SOURCE_RECORD"
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
        return [dict(zip(cols, r, strict=True)) for r in self.con.execute(sql, params).fetchall()]

    def vocab(self) -> set[str]:
        return {r[0].strip().lower() for r in self.con.execute("SELECT pt_name FROM REF.PT_VOCAB").fetchall()}

    def start_run(self, provider: str, prompt_version: str, code_version: str, scope: dict) -> str:
        run_id = f"run-{uuid.uuid4().hex[:12]}"
        self.con.execute("INSERT INTO SWEEP.RUN (run_id, started_at, provider, prompt_version, code_version, scope, status) "
                         "VALUES (?, current_timestamp, ?, ?, ?, ?, 'running')",
                         [run_id, provider, prompt_version, code_version, json.dumps(scope)])
        return run_id

    def finish_run(self, run_id: str, counts: dict, cost_usd: float, status: str):
        self.con.execute("UPDATE SWEEP.RUN SET finished_at = current_timestamp, counts = ?, cost_usd = ?, status = ? WHERE run_id = ?",
                         [json.dumps(counts), cost_usd, status, run_id])

    def insert_screening(self, run_id, record_id, cls, criteria, evidence, confidence, result):
        self.con.execute("INSERT INTO SWEEP.SCREENING (run_id, record_id, screening_class, criteria_patient, criteria_reporter, "
                         "criteria_product, criteria_event, evidence, confidence, result) VALUES (?,?,?,?,?,?,?,?,?,?)",
                         [run_id, record_id, cls, criteria.get("identifiable_patient"), criteria.get("identifiable_reporter"),
                          criteria.get("suspect_product"), criteria.get("event"), json.dumps(evidence), confidence, json.dumps(result)])

    def insert_extraction(self, run_id, record_id, result, valid, problems, tier):
        self.con.execute("INSERT INTO SWEEP.EXTRACTION (run_id, record_id, result, valid, problems, model_tier) VALUES (?,?,?,?,?,?)",
                         [run_id, record_id, json.dumps(result), valid, json.dumps(problems), tier])

    def insert_rule_result(self, run_id, record_id, r: dict):
        cols = ["ownership", "substance", "report_type", "causality_required", "ime_flag", "serious", "criteria_complete",
                "proposed_day0", "regulatory_deadline", "days_remaining", "regulatory_status", "forwarding_days", "forwarding_status"]
        self.con.execute(f"INSERT INTO SWEEP.RULE_RESULT (run_id, record_id, {', '.join(cols)}) VALUES (?, ?, {', '.join('?' * len(cols))})",
                         [run_id, record_id, *[r[c] for c in cols]])

    def insert_candidates(self, run_id, record_id, cands: list[dict]):
        for c in cands:
            self.con.execute("INSERT INTO SWEEP.MATCH_CANDIDATE VALUES (?,?,?,?,?)",
                             [run_id, record_id, c["source"], c["candidate_id"], json.dumps(c["keys"])])

    def insert_match_decision(self, run_id, record_id, d: dict):
        self.con.execute("INSERT INTO SWEEP.MATCH_DECISION (run_id, record_id, outcome, matched_ids, new_facts, justification, "
                         "confidence, tool_calls, agent_name, agent_version, valid) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                         [run_id, record_id, d["outcome"], json.dumps(d.get("matched_ids", [])), json.dumps(d.get("new_facts", [])),
                          d.get("justification"), d.get("confidence"), json.dumps(d.get("tool_calls", [])), d.get("agent_name"),
                          d.get("agent_version"), d.get("valid", True)])

    def channel_meta(self) -> dict:
        """Channel report type and vendor forwarding timelines; mirrors REF.CHANNEL and REF.VENDOR."""
        return {"MI": ("spontaneous", "MIV", 1), "CRM": ("spontaneous", None, None), "PSP": ("solicited", "PSPV", 1),
                "PQC": ("spontaneous", None, None), "SOCIAL": ("solicited", "SOCV", 2)}

    def ime_terms(self) -> set[str]:
        # Keep identical to the demo list in snowflake/migrations/V003__seed_ref.sql.
        return {t.lower() for t in ("Serotonin syndrome", "Hyponatraemia", "Electrocardiogram QT prolonged", "Torsade de pointes",
                                    "Arrhythmia", "Suicidal ideation", "Suicide attempt", "Completed suicide", "Seizure",
                                    "Gastrointestinal haemorrhage", "Hepatic failure", "Neuroleptic malignant syndrome",
                                    "Anaphylactic reaction", "Stevens-Johnson syndrome", "Agranulocytosis", "Rhabdomyolysis",
                                    "Syncope", "Self-harm ideation", "Self-injurious ideation", "Suicidal thoughts",
                                    "QT prolonged", "QT prolongation", "Loss of consciousness", "Fainting")}

    def insert_model_call(self, row: dict):
        cols = ["call_id", "run_id", "record_id", "step", "provider", "deployment", "agent_name", "agent_version", "prompt_version",
                "schema_version", "effort", "input_hash", "output_hash", "raw_output", "input_tokens", "output_tokens",
                "cached_tokens", "latency_ms", "status", "error"]
        self.con.execute(f"INSERT INTO AUDIT.MODEL_CALL ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                         [row.get(c) for c in cols])

    def query(self, sql: str, params=None):
        return self.con.execute(sql, params or []).fetchall()


def _locked(fn):
    def wrapper(self, *args, **kwargs):
        with self.lock:
            return fn(self, *args, **kwargs)
    wrapper.__name__ = fn.__name__
    return wrapper


# DuckDB connections are not thread-safe; the sweep runs model calls in threads, so writes are serialised.
for _name in ("records", "vocab", "start_run", "finish_run", "insert_screening", "insert_extraction", "insert_rule_result",
              "insert_candidates", "insert_match_decision", "insert_model_call", "query"):
    setattr(LocalStore, _name, _locked(getattr(LocalStore, _name)))
