"""Smoke test of the review app (databricks/app/app.py) in local DuckDB mode with Streamlit's AppTest.

    uv run --no-project -p 3.11 --with streamlit==1.38.0 --with duckdb --with pandas \
        python -I databricks/app/smoke_test.py [--db data/local/findings-test.duckdb]

The database is copied to a temporary file first; the original is never opened. Checks: every page renders for
every sweep run without an exception, and recording outcome D writes the decision, the case intake package and a
compliance finding (a late submission with a past day 0 on the latest run, a forwarding breach on the first run whose
top finding carries a compliance note). Not part of the deployed app: scripts/dbx_app.py uploads only app.py,
app.yaml and requirements.txt.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
PAGES = ["Review queue", "Reconciliation", "Channel KPIs", "Model comparison", "QC sample"]
# st.error output the app shows by design for packages with a passed deadline or a forwarding breach.
EXPECTED_ERRORS = ("deadline passed", "Forwarding timeline")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "local" / "findings-test.duckdb"))
    args = ap.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="pvsweep-apptest-"))
    db = tmp / "smoke.duckdb"
    shutil.copyfile(args.db, db)
    os.environ["PVSWEEP_LOCAL_DB"] = str(db)

    import duckdb
    import streamlit
    from streamlit.testing.v1 import AppTest

    print(f"streamlit {streamlit.__version__}, python {sys.version.split()[0]}, db copy {db}")
    fails = 0

    def check(cond: bool, msg: str) -> None:
        nonlocal fails
        print(("PASS " if cond else "FAIL ") + msg)
        fails += 0 if cond else 1

    at = AppTest.from_file(str(HERE / "app.py"), default_timeout=60).run()
    check(not at.exception, f"initial render {[e.value for e in at.exception]}")
    if at.exception:
        return 1
    runs = [o.split(" ")[0] for o in at.sidebar.selectbox[0].options]
    for run in runs:
        at.sidebar.selectbox[0].set_value(run).run()
        for page in PAGES:
            at.sidebar.radio[0].set_value(page).run()
            unexpected = [e.value for e in at.error if not any(x in e.value for x in EXPECTED_ERRORS)]
            check(not at.exception and not unexpected,
                  f"{run} / {page}: exceptions={[e.value for e in at.exception]} errors={unexpected} "
                  f"dataframes={len(at.dataframe)}")

    def record_d(run_id: str, day0: dt.date | None = None, root: str | None = None) -> str:
        at.sidebar.selectbox[0].set_value(run_id).run()
        at.sidebar.radio[0].set_value("Review queue").run()
        fid = next(s for s in at.selectbox if s.label == "Open finding").value   # top-priority finding
        at.radio(key=f"{fid}-outcome").set_value("D_VALID_ICSR").run()
        if day0 is not None:
            at.date_input(key=f"{fid}-day0").set_value(day0).run()
        if root is not None and any(s.key == f"{fid}-root" for s in at.selectbox):
            at.selectbox(key=f"{fid}-root").set_value(root).run()
        at.text_area(key=f"{fid}-rationale").set_value("smoke test").run()
        at.button(key=f"{fid}-save").click().run()
        check(not at.exception and len(at.success) == 1,
              f"record D on {fid}: {[s.value for s in at.success]} {[e.value for e in at.exception]}")
        return fid

    con = duckdb.connect(str(db))   # same process: shares the database instance the app opened
    breach_run = next((r for r, in con.execute(
        "SELECT run_id FROM SWEEP.FINDING WHERE json_extract_string(package, '$.compliance_note') IS NOT NULL "
        "ORDER BY run_id").fetchall()), None)
    targets = [(record_d(runs[0], day0=dt.date.today() - dt.timedelta(days=200), root="not_forwarded"), "late_submission")]
    if breach_run:
        targets.append((record_d(breach_run), "forwarding_breach"))

    for fid, kind in targets:
        d = con.execute("SELECT decision_id, reviewer, outcome FROM REVIEW.DECISION WHERE finding_id = ?", [fid]).fetchall()
        p = con.execute("SELECT decision_id, late_submission, package FROM REVIEW.CASE_INTAKE_PACKAGE WHERE finding_id = ?",
                        [fid]).fetchall()
        c = [k for k, in con.execute("SELECT kind FROM REVIEW.COMPLIANCE_FINDING WHERE finding_id = ?", [fid]).fetchall()]
        check(len(d) == 1 and d[0][2] == "D_VALID_ICSR", f"{fid}: decision row {d}")
        check(len(p) == 1 and p[0][0] == d[0][0] and json.loads(p[0][2])["review"]["decision_id"] == d[0][0],
              f"{fid}: case intake package linked to the decision (late_submission={p[0][1] if p else None})")
        check(kind in c, f"{fid}: compliance finding {c} includes {kind}")

    print(f"{fails} failure(s)")
    shutil.rmtree(tmp, ignore_errors=True)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
