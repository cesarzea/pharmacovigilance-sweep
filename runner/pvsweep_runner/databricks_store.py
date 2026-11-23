"""Databricks SQL warehouse backend for the runner: same interface as LocalStore and SnowflakeStore.

Connection: `databricks-sql-connector` 4.8.0 (`from databricks import sql`) against a SQL warehouse.

    PVSWEEP_DATABRICKS_HOST       workspace host, adb-<id>.<n>.azuredatabricks.net (an https:// prefix is accepted)
    PVSWEEP_DATABRICKS_HTTP_PATH  the warehouse HTTP path, /sql/1.0/warehouses/<id>
    PVSWEEP_DATABRICKS_CATALOG    Unity Catalog catalog holding SRC, SWEEP, AUDIT, ... (default pvsweep)

Authentication is a Microsoft Entra access token for the Azure Databricks resource (scope
2ff814a6-3304-4ab8-85cb-cd0e6f879c1d/.default), obtained with azure-identity and handed to the connector
through `credentials_provider`. No personal access tokens. The credential is chosen from the environment:

- PVSWEEP_DATABRICKS_CLIENT_ID + PVSWEEP_DATABRICKS_CLIENT_SECRET: an Entra service principal (client secret),
  with the tenant in PVSWEEP_DATABRICKS_TENANT_ID or AZURE_TENANT_ID;
- PVSWEEP_DATABRICKS_CLIENT_ID alone: a user-assigned managed identity with that client id (the job);
- neither: DefaultAzureCredential without the interactive browser, which on a laptop is the Azure CLI login
  and in Azure a managed or workload identity.

The in-process matching agent (pvsweep_agent.backend.DatabricksBackend) uses the same helper and prefers
PVSWEEP_DATABRICKS_AGENT_CLIENT_ID / _SECRET when set, so it can run as its own read-only principal.

Parameters: connector 4.x binds natively (server side) and accepts PEP-249 positional `?` markers with a list
of plain Python values, so the runner's SQL is sent as written. `_bind` checks it (no `?` inside literals or
comments, one value per marker) and inlines a trailing `LIMIT ?` as an integer literal. Dates and timestamps
bind as Python date/datetime. `use_inline_params` is never enabled (client-side string rendering).

JSON columns: values are written through JSON_INPUT, `parse_json(...)` for VARIANT columns; set it to "{}" if
the tables declare those columns as STRING with JSON text. Reading `col:path::string` works for both.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid

DATABRICKS_SCOPE = "2ff814a6-3304-4ab8-85cb-cd0e6f879c1d/.default"   # the Azure Databricks first-party application
DEFAULT_CATALOG = "pvsweep"

# How a JSON text parameter becomes a column value: VARIANT columns (parse_json) or STRING columns ("{}").
JSON_INPUT = "parse_json({})"
# A None in a JSON slot would bind as VOID; the cast gives parse_json a typed NULL.
_JSON_SLOT = JSON_INPUT.format("CAST(? AS STRING)")

_TRAILING_LIMIT = re.compile(r"\bLIMIT\s+\?\s*;?\s*$", re.IGNORECASE)


# ---- connection -------------------------------------------------------------------------------------

def credential(prefix: str = "PVSWEEP_DATABRICKS"):
    """The azure-identity credential for a principal described by <prefix>_CLIENT_ID / _CLIENT_SECRET."""
    from azure.identity import ClientSecretCredential, DefaultAzureCredential, ManagedIdentityCredential

    client_id, secret = os.environ.get(f"{prefix}_CLIENT_ID"), os.environ.get(f"{prefix}_CLIENT_SECRET")
    if client_id and secret:
        tenant = os.environ.get("PVSWEEP_DATABRICKS_TENANT_ID") or os.environ.get("AZURE_TENANT_ID")
        if not tenant:
            raise SystemExit(f"{prefix}_CLIENT_SECRET is set: PVSWEEP_DATABRICKS_TENANT_ID (or AZURE_TENANT_ID) is required")
        return ClientSecretCredential(tenant_id=tenant, client_id=client_id, client_secret=secret)
    if client_id:
        return ManagedIdentityCredential(client_id=client_id)
    return DefaultAzureCredential(exclude_interactive_browser_credential=True)


class EntraHeaders:
    """Header factory for the connector: a bearer token, refreshed five minutes before it expires
    (the Azure CLI credential does not cache tokens itself)."""

    def __init__(self, cred, scope: str = DATABRICKS_SCOPE):
        self._cred, self._scope = cred, scope
        self._token = None
        self._lock = threading.Lock()

    def __call__(self) -> dict[str, str]:
        with self._lock:
            if self._token is None or self._token.expires_on - time.time() < 300:
                self._token = self._cred.get_token(self._scope)
            return {"Authorization": f"Bearer {self._token.token}"}


def connect(agent: bool = False):
    """Open a warehouse connection. agent=True prefers the agent principal (PVSWEEP_DATABRICKS_AGENT_*)."""
    from databricks import sql

    prefix = "PVSWEEP_DATABRICKS_AGENT" if agent and os.environ.get("PVSWEEP_DATABRICKS_AGENT_CLIENT_ID") else "PVSWEEP_DATABRICKS"
    headers = EntraHeaders(credential(prefix))
    host = re.sub(r"^https?://", "", os.environ["PVSWEEP_DATABRICKS_HOST"]).rstrip("/")
    return sql.connect(
        server_hostname=host, http_path=os.environ["PVSWEEP_DATABRICKS_HTTP_PATH"],
        credentials_provider=lambda: headers,   # the connector calls this once and the factory per request
        catalog=os.environ.get("PVSWEEP_DATABRICKS_CATALOG", DEFAULT_CATALOG),
    )


# ---- parameters -------------------------------------------------------------------------------------

def _markers(sql: str) -> list[int]:
    """Positions of `?` markers outside string literals, quoted identifiers and comments. A `?` inside any of
    those is a bug in the caller's SQL (it would be bound, or silently not), so it raises."""
    out: list[int] = []
    i, n = 0, len(sql)
    while i < n:
        c = sql[i]
        if c in ("'", '"', "`"):
            j = i + 1
            while j < n:
                if sql[j] == "\\" and c != "`":
                    j += 2
                    continue
                if sql[j] == c:
                    if j + 1 < n and sql[j + 1] == c:   # doubled quote
                        j += 2
                        continue
                    break
                j += 1
            if j >= n:
                raise ValueError(f"unterminated {c} in SQL: {sql[:120]}")
            if "?" in sql[i:j + 1]:
                raise ValueError(f"'?' inside a quoted literal or identifier: {sql[i:j + 1]}")
            i = j + 1
        elif sql.startswith("--", i):
            j = sql.find("\n", i)
            j = n if j < 0 else j
            if "?" in sql[i:j]:
                raise ValueError("'?' inside a SQL comment")
            i = j
        elif sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            j = n if j < 0 else j + 2
            if "?" in sql[i:j]:
                raise ValueError("'?' inside a SQL comment")
            i = j
        else:
            if c == "?":
                out.append(i)
            i += 1
    return out


def _bind(sql: str, params=None) -> tuple[str, list | None]:
    """Check the runner's qmark SQL and return (sql, params) for the connector's native positional binding.

    A trailing `LIMIT ?` becomes an integer literal (Databricks does not bind LIMIT); any other `LIMIT ?`
    raises. Returns None for params when there are none, so the connector sends the text unparameterised."""
    params = list(params or [])
    marks = _markers(sql)
    if len(marks) != len(params):
        raise ValueError(f"SQL has {len(marks)} '?' markers but {len(params)} parameters")
    m = _TRAILING_LIMIT.search(sql)
    if m:
        limit = params.pop()
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
            raise ValueError(f"LIMIT parameter must be a non-negative int, got {limit!r}")
        sql = f"{sql[:m.start()]}LIMIT {limit}"
        marks = marks[:-1]
    if any(re.search(r"\bLIMIT\s*$", sql[:p], re.IGNORECASE) for p in marks):
        raise ValueError("LIMIT ? is only supported at the end of the statement")
    return sql, (params or None)


def _json(value, **kw) -> str | None:
    return None if value is None else json.dumps(value, **kw)


# ---- store ------------------------------------------------------------------------------------------

class DatabricksStore:
    dialect = "databricks"

    def __init__(self, con=None):
        self.con = con if con is not None else connect()
        self.lock = threading.RLock()

    def _exec(self, sql: str, params=None):
        """Execute and return the open cursor (the caller fetches and closes it; snapshot.copy_run uses this)."""
        sql, bound = _bind(sql, params)
        with self.lock:
            cur = self.con.cursor()
            try:
                cur.execute(sql, bound)
                return cur
            except Exception:
                cur.close()
                raise

    def query(self, sql: str, params=None):
        with self.lock:   # one connection shared by the sweep's threads: execute and fetch together
            cur = self._exec(sql, params)
            try:
                return [tuple(r) for r in cur.fetchall()]
            finally:
                cur.close()

    def _run(self, sql: str, params=None) -> None:
        self._exec(sql, params).close()

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
        # started_at is set explicitly: Delta column defaults need a table feature, and runs are ordered by it.
        run_id = f"run-{uuid.uuid4().hex[:12]}"
        self._run("INSERT INTO SWEEP.RUN (run_id, started_at, provider, prompt_version, code_version, scope, status) "
                  f"SELECT ?, CURRENT_TIMESTAMP(), ?, ?, ?, {_JSON_SLOT}, 'running'",
                  [run_id, provider, prompt_version, code_version, json.dumps(scope)])
        return run_id

    def finish_run(self, run_id, counts, cost_usd, status):
        self._run(f"UPDATE SWEEP.RUN SET finished_at = CURRENT_TIMESTAMP(), counts = {_JSON_SLOT}, cost_usd = ?, status = ? "
                  "WHERE run_id = ?", [json.dumps(counts), cost_usd, status, run_id])

    def insert_screening(self, run_id, record_id, cls, criteria, evidence, confidence, result):
        self._run("INSERT INTO SWEEP.SCREENING (run_id, record_id, screening_class, criteria_patient, criteria_reporter, "
                  "criteria_product, criteria_event, evidence, confidence, result) "
                  f"SELECT ?, ?, ?, ?, ?, ?, ?, {_JSON_SLOT}, ?, {_JSON_SLOT}",
                  [run_id, record_id, cls, criteria.get("identifiable_patient"), criteria.get("identifiable_reporter"),
                   criteria.get("suspect_product"), criteria.get("event"), json.dumps(evidence), confidence, json.dumps(result)])

    def insert_extraction(self, run_id, record_id, result, valid, problems, tier):
        self._run("INSERT INTO SWEEP.EXTRACTION (run_id, record_id, result, valid, problems, model_tier) "
                  f"SELECT ?, ?, {_JSON_SLOT}, ?, {_JSON_SLOT}, ?",
                  [run_id, record_id, json.dumps(result), valid, json.dumps(problems), tier])

    def insert_rule_result(self, run_id, record_id, r: dict):
        cols = ["ownership", "substance", "report_type", "causality_required", "ime_flag", "serious", "criteria_complete",
                "proposed_day0", "regulatory_deadline", "days_remaining", "regulatory_status", "forwarding_days", "forwarding_status"]
        self._run(f"INSERT INTO SWEEP.RULE_RESULT (run_id, record_id, {', '.join(cols)}) VALUES (?, ?, {', '.join('?' * len(cols))})",
                  [run_id, record_id, *[r[c] for c in cols]])

    def insert_candidates(self, run_id, record_id, cands):
        # One statement (one Delta commit) per record rather than per candidate.
        if not cands:
            return
        select = f"SELECT ?, ?, ?, ?, {_JSON_SLOT}"
        params: list = []
        for c in cands:
            params += [run_id, record_id, c["source"], c["candidate_id"], json.dumps(c["keys"])]
        self._run("INSERT INTO SWEEP.MATCH_CANDIDATE (run_id, record_id, source, candidate_id, blocking_keys) "
                  + " UNION ALL ".join([select] * len(cands)), params)

    def insert_match_decision(self, run_id, record_id, d: dict):
        self._run("INSERT INTO SWEEP.MATCH_DECISION (run_id, record_id, outcome, matched_ids, new_facts, justification, confidence, "
                  "tool_calls, agent_name, agent_version, valid) "
                  f"SELECT ?, ?, ?, {_JSON_SLOT}, {_JSON_SLOT}, ?, ?, {_JSON_SLOT}, ?, ?, ?",
                  [run_id, record_id, d["outcome"], json.dumps(d.get("matched_ids", [])), json.dumps(d.get("new_facts", [])),
                   d.get("justification"), d.get("confidence"), json.dumps(d.get("tool_calls", []), default=str), d.get("agent_name"),
                   d.get("agent_version"), d.get("valid", True)])

    def insert_findings(self, run_id, rows: list[dict]):
        if not rows:
            return
        select = f"SELECT ?, ?, ?, ?, ?, ?, ?, {_JSON_SLOT}"
        params: list = []
        for f in rows:
            params += [run_id, f["finding_id"], f["record_id"], f["finding_type"], f["priority"], f.get("summary"), f.get("note"),
                       _json(f.get("package"), sort_keys=True, default=str)]
        self._run("INSERT INTO SWEEP.FINDING (run_id, finding_id, record_id, finding_type, priority, summary, note, package) "
                  + " UNION ALL ".join([select] * len(rows)), params)

    def insert_model_call(self, row: dict):
        cols = ["call_id", "run_id", "record_id", "step", "provider", "deployment", "agent_name", "agent_version", "prompt_version",
                "schema_version", "effort", "input_hash", "output_hash", "input_tokens", "output_tokens", "cached_tokens",
                "latency_ms", "status", "error"]
        self._run(f"INSERT INTO AUDIT.MODEL_CALL ({', '.join(cols)}, raw_output) SELECT {', '.join('?' * len(cols))}, {_JSON_SLOT}",
                  [*[row.get(c) for c in cols], row.get("raw_output") or "null"])
