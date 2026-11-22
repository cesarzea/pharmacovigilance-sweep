import duckdb

from pvsweep_runner import store


def test_report_views_from_v007_run_on_duckdb():
    stmts = store.report_view_statements()
    names = [s.split()[4] for s in stmts]   # CREATE OR REPLACE VIEW <name> AS
    assert names == ["REPORT.RECONCILIATION", "REPORT.RECONCILIATION_SUMMARY", "REPORT.CHANNEL_KPI",
                     "REPORT.MODEL_COMPARISON"]
    con = duckdb.connect()
    store.ensure_local_schema(con)
    store.ensure_local_schema(con)   # idempotent
    for name in names:
        assert con.execute(f"SELECT count(*) FROM {name}").fetchone() == (0,)


def test_local_schema_has_review_tables_and_finding_columns():
    con = duckdb.connect()
    con.execute("CREATE SCHEMA SWEEP; CREATE TABLE SWEEP.FINDING (run_id VARCHAR, finding_id VARCHAR PRIMARY KEY, "
                "record_id VARCHAR, finding_type VARCHAR, priority INTEGER, created_at TIMESTAMP)")   # pre-V009 file
    store.ensure_local_schema(con)
    cols = {r[0] for r in con.execute("SELECT column_name FROM information_schema.columns "
                                      "WHERE table_schema = 'SWEEP' AND table_name = 'FINDING'").fetchall()}
    assert {"summary", "note", "package"} <= cols
    tables = {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'REVIEW'")
              .fetchall()}
    assert {"DECISION", "CASE_INTAKE_PACKAGE", "COMPLIANCE_FINDING"} <= tables
