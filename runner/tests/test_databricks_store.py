"""DatabricksStore and DatabricksBackend against a fake connection: SQL shape and parameters, no network."""

import datetime as dt
import json

import pytest

from pvsweep_agent.backend import DatabricksBackend, DuckDBBackend, SnowflakeBackend, from_env
from pvsweep_runner import blocking
from pvsweep_runner import databricks_store as D
from pvsweep_runner.__main__ import json_string
from pvsweep_runner.databricks_store import DatabricksStore, _bind


class FakeCursor:
    def __init__(self, con):
        self.con = con
        self.description = None
        self.closed = False

    def execute(self, sql, params=None):
        self.con.executed.append((sql, params))
        rows, desc = self.con.results.pop(0) if self.con.results else ([], [("x", "string")])
        self._rows, self.description = rows, desc

    def fetchall(self):
        return list(self._rows)

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, results=None):
        self.executed: list[tuple[str, list | None]] = []
        self.results = list(results or [])

    def cursor(self):
        return FakeCursor(self)


def store(results=None):
    return DatabricksStore(con=FakeConnection(results))


# ---- _bind ------------------------------------------------------------------------------------------

def test_bind_passes_positional_markers_through():
    sql, params = _bind("SELECT a FROM t WHERE b = ? AND c BETWEEN ? AND ?", ["x", dt.date(2026, 1, 1), dt.date(2026, 2, 1)])
    assert sql == "SELECT a FROM t WHERE b = ? AND c BETWEEN ? AND ?"
    assert params == ["x", dt.date(2026, 1, 1), dt.date(2026, 2, 1)]


def test_bind_without_params_sends_none():
    assert _bind("SELECT 1") == ("SELECT 1", None)
    assert _bind("SELECT 1", []) == ("SELECT 1", None)


def test_bind_inlines_trailing_limit():
    sql, params = _bind("SELECT a FROM t WHERE b = ?\nORDER BY a\nLIMIT ?", ["x", 60])
    assert sql.endswith("LIMIT 60")
    assert "?" not in sql.split("WHERE")[1].replace("b = ?", "")
    assert params == ["x"]
    assert _bind("SELECT a FROM t limit ?", [5]) == ("SELECT a FROM t LIMIT 5", None)


@pytest.mark.parametrize("bad", ["60", 1.5, True, -1, None])
def test_bind_rejects_non_int_limit(bad):
    with pytest.raises(ValueError):
        _bind("SELECT a FROM t LIMIT ?", [bad])


def test_bind_rejects_limit_marker_elsewhere():
    with pytest.raises(ValueError):
        _bind("SELECT * FROM (SELECT a FROM t LIMIT ?) WHERE a = ?", [3, "x"])


def test_bind_counts_markers():
    with pytest.raises(ValueError):
        _bind("SELECT ? , ?", ["only one"])


@pytest.mark.parametrize("sql", ["SELECT 'is it?' WHERE a = ?", 'SELECT "a?" WHERE a = ?', "SELECT `c?` FROM t WHERE a = ?",
                                 "SELECT a -- why?\nFROM t WHERE a = ?", "SELECT /* ? */ a FROM t WHERE a = ?"])
def test_bind_rejects_marker_inside_literal_or_comment(sql):
    with pytest.raises(ValueError):
        _bind(sql, ["x"])


def test_bind_ignores_quotes_without_markers():
    sql = "SELECT 'it''s', e.result:patient.sex::string FROM t WHERE run_id = ? AND x LIKE '%a%'"
    assert _bind(sql, ["r"]) == (sql, ["r"])


def test_blocking_case_sql_binds():
    """blocking._CASE_SQL is the one statement with a bound LIMIT; it must bind with the limit inlined."""
    params = ["sertraline", "female", "female", 40, 39, 41, dt.date(2026, 9, 1), dt.date(2026, 10, 1), blocking.SQL_FETCH]
    sql, bound = _bind(blocking._CASE_SQL, params)
    assert sql.endswith(f"LIMIT {blocking.SQL_FETCH}")
    assert bound == params[:-1]
    assert sql.count("?") == len(bound)


def test_blocking_runs_through_store_query():
    s = store()
    blocking.candidates(s, substance="sertraline", sex="female", age=40, terms=["Nausea"],
                        channel_received=dt.date(2026, 10, 1), vendor_code="PSPV", vendor_reference="R1",
                        product_name="Sertavix")
    sqls = [sql for sql, _ in s.con.executed]
    assert len(sqls) == 4   # exact pass, ranked pass, vendor log, intake queue
    assert sqls[0].endswith(f"LIMIT {blocking.SQL_FETCH}")
    for sql, params in s.con.executed:
        assert sql.count("?") == len(params or [])


# ---- store writes ------------------------------------------------------------------------------------

def test_insert_screening_shape():
    s = store()
    s.insert_screening("run-1", "PSP-1", "ADVERSE_EVENT", {"identifiable_patient": True, "event": True}, [{"q": "x"}], "high",
                       {"screening_class": "ADVERSE_EVENT"})
    sql, params = s.con.executed[0]
    assert sql.startswith("INSERT INTO SWEEP.SCREENING (run_id, record_id, screening_class,")
    assert " SELECT ?, ?, ?, ?, ?, ?, ?, parse_json(CAST(? AS STRING)), ?, parse_json(CAST(? AS STRING))" in sql
    assert "VALUES" not in sql
    assert params == ["run-1", "PSP-1", "ADVERSE_EVENT", True, None, None, True, json.dumps([{"q": "x"}]), "high",
                      json.dumps({"screening_class": "ADVERSE_EVENT"})]


def test_json_input_is_the_single_switch():
    assert D.JSON_INPUT == "parse_json({})"
    assert D._JSON_SLOT == "parse_json(CAST(? AS STRING))"


def test_insert_findings_one_statement_with_null_package():
    s = store()
    rows = [{"finding_id": "f1", "record_id": "PSP-1", "finding_type": "potential_case", "priority": 300, "summary": "s",
             "note": None, "package": {"b": 1, "a": dt.date(2026, 1, 2)}},
            {"finding_id": "f2", "record_id": "PSP-2", "finding_type": "qc_sample", "priority": 1, "package": None}]
    s.insert_findings("run-1", rows)
    assert len(s.con.executed) == 1
    sql, params = s.con.executed[0]
    assert sql.startswith("INSERT INTO SWEEP.FINDING (run_id, finding_id, record_id, finding_type, priority, summary, note, package) ")
    assert sql.count("UNION ALL") == 1
    assert sql.count("parse_json(CAST(? AS STRING))") == 2
    assert params[:8] == ["run-1", "f1", "PSP-1", "potential_case", 300, "s", None, '{"a": "2026-01-02", "b": 1}']
    assert params[8:] == ["run-1", "f2", "PSP-2", "qc_sample", 1, None, None, None]
    s.insert_findings("run-1", [])
    assert len(s.con.executed) == 1


def test_insert_candidates_one_statement():
    s = store()
    s.insert_candidates("run-1", "PSP-1", [{"source": "safety_db", "candidate_id": "C1", "keys": {"a": 1}},
                                          {"source": "vendor_log", "candidate_id": "V/1", "keys": {}}])
    sql, params = s.con.executed[0]
    assert sql.count("UNION ALL") == 1 and len(params) == 10 and sql.count("?") == 10


def test_start_and_finish_run():
    s = store()
    run_id = s.start_run("gpt", "screen:v1", "abc", {"as_of": "2026-10-31"})
    sql, params = s.con.executed[0]
    assert "started_at" in sql and "CURRENT_TIMESTAMP()" in sql
    assert params == [run_id, "gpt", "screen:v1", "abc", '{"as_of": "2026-10-31"}']
    s.finish_run(run_id, {"screened": 1}, 0.5, "finished")
    sql, params = s.con.executed[1]
    assert sql.startswith("UPDATE SWEEP.RUN SET finished_at = CURRENT_TIMESTAMP(), counts = parse_json(")
    assert params == ['{"screened": 1}', 0.5, "finished", run_id]


def test_insert_model_call_raw_output_defaults_to_json_null():
    s = store()
    s.insert_model_call({"call_id": "c", "run_id": "r", "input_tokens": 10})
    sql, params = s.con.executed[0]
    assert sql.startswith("INSERT INTO AUDIT.MODEL_CALL (call_id,") and sql.endswith("parse_json(CAST(? AS STRING))")
    assert len(params) == 20 and params[-1] == "null" and params[13] == 10


def test_insert_rule_result_values_with_dates():
    s = store()
    rule = {c: None for c in ["ownership", "substance", "report_type", "causality_required", "ime_flag", "serious",
                              "criteria_complete", "regulatory_deadline", "days_remaining", "regulatory_status", "forwarding_days",
                              "forwarding_status"]}
    rule["proposed_day0"] = dt.date(2026, 10, 20)
    s.insert_rule_result("r", "PSP-1", rule)
    sql, params = s.con.executed[0]
    assert sql.count("?") == 15 and len(params) == 15 and dt.date(2026, 10, 20) in params


# ---- store reads -------------------------------------------------------------------------------------

def test_records_filters_and_limit():
    row = ("PSP-1", "PSP", dt.date(2026, 10, 1), "SE", "PSPV", "R1", "text")
    s = store([([row], [])])
    out = s.records(["PSP", "MI"], 5, ["PSP-1"])
    sql, params = s.con.executed[0]
    assert "WHERE channel_code IN (?,?) AND record_id IN (?)" in sql
    assert sql.endswith("ORDER BY record_id LIMIT 5")
    assert params == ["PSP", "MI", "PSP-1"]
    assert out == [{"record_id": "PSP-1", "channel_code": "PSP", "channel_received_date": dt.date(2026, 10, 1), "country": "SE",
                    "vendor_code": "PSPV", "vendor_reference": "R1", "record_text": "text"}]


def test_records_without_filters():
    s = store()
    s.records(None, None, None)
    sql, params = s.con.executed[0]
    assert "WHERE" not in sql and "LIMIT" not in sql and params is None


def test_query_closes_cursor_and_returns_tuples():
    s = store([([["a", 1]], [])])
    assert s.query("SELECT ?, 1", ["a"]) == [("a", 1)]


# ---- dialect selection -------------------------------------------------------------------------------

def test_json_string_by_dialect():
    assert json_string(store())("e.result", "patient.sex") == "e.result:patient.sex::string"

    class Local:
        dialect = "duckdb"

    assert json_string(Local())("e.result", "patient.sex") == "json_extract_string(e.result, '$.patient.sex')"


def test_backend_rows_normalises_nested_columns():
    class Arr:   # stands in for a numpy array (pyarrow result path)
        def __init__(self, v):
            self.v = v

        def tolist(self):
            return list(self.v)

    desc = [("CASE_ID", "string"), ("SUBSTANCES", "array"), ("EVENTS", "array"), ("NOTE", "string")]
    con = FakeConnection([([("C1", '["sertraline"]', Arr(["Nausea"]), '["kept as text"]')], desc)])
    b = DatabricksBackend(con=con)
    assert b.dialect == "databricks"
    rows = b.rows("SELECT case_id FROM AGENT_API.SAFETY_CASE_SUMMARY WHERE array_contains(substances, ?) LIMIT ?",
                  ["sertraline", 40])
    assert rows == [{"case_id": "C1", "substances": ["sertraline"], "events": ["Nausea"], "note": '["kept as text"]'}]
    sql, params = con.executed[0]
    assert sql.endswith("LIMIT 40") and params == ["sertraline"]


def test_from_env_selects_platform(monkeypatch):
    made = []
    monkeypatch.setattr(DuckDBBackend, "__init__", lambda self, con: made.append("duckdb"))
    monkeypatch.setenv("PVSWEEP_PLATFORM", "databricks")
    assert isinstance(from_env(object()), DuckDBBackend)   # a local connection wins whatever the platform
    monkeypatch.setattr(DatabricksBackend, "__init__", lambda self: made.append("databricks"))
    monkeypatch.setattr(SnowflakeBackend, "__init__", lambda self: made.append("snowflake"))
    monkeypatch.setenv("PVSWEEP_PLATFORM", "databricks")
    assert isinstance(from_env(), DatabricksBackend)
    monkeypatch.delenv("PVSWEEP_PLATFORM")
    assert isinstance(from_env(), SnowflakeBackend)
    monkeypatch.setenv("PVSWEEP_PLATFORM", "oracle")
    with pytest.raises(ValueError):
        from_env()
    assert made == ["duckdb", "databricks", "snowflake"]


def test_matcher_uses_array_contains_on_databricks():
    from pvsweep_agent.matcher import Context, make_tools

    class Recorder:
        dialect = "databricks"

        def __init__(self):
            self.sql = []

        def rows(self, sql, params):
            self.sql.append((sql, params))
            return []

    b = Recorder()
    tools = make_tools(b, Context(), set())
    search = next(t for t in tools if t.name == "search_safety_cases")
    search.func("Sertraline", sex="female")
    sql, params = b.sql[0]
    assert "WHERE array_contains(substances, ?)" in sql and params == ["sertraline", "female"]


def test_credentials_provider_header_factory_caches_token():
    class Tok:
        def __init__(self, n):
            self.token, self.expires_on = f"t{n}", 10**12

    class Cred:
        n = 0

        def get_token(self, scope):
            assert scope == D.DATABRICKS_SCOPE
            self.n += 1
            return Tok(self.n)

    cred = Cred()
    headers = D.EntraHeaders(cred)
    assert headers() == {"Authorization": "Bearer t1"}
    assert headers() == {"Authorization": "Bearer t1"} and cred.n == 1
