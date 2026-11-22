"""Pharmacovigilance Sweep: review app (Streamlit in Snowflake; runs locally over DuckDB for development).

The app makes no model calls. It shows what the sweep produced, walks the reviewer through the
checklist and records the decision (append-only, with the viewer's user name).

Local development:  PVSWEEP_LOCAL_DB=data/local/pvsweep.duckdb streamlit run snowflake/streamlit/app.py
"""

from __future__ import annotations

import datetime as dt
import json
import os
import uuid

import pandas as pd
import streamlit as st

OUTCOMES = {
    "A_NOT_REPORTABLE": "A. Not reportable: no adverse event, or solicited event assessed as not related",
    "B_ALREADY_RECEIVED": "B. Already received, no new significant information",
    "C_INCOMPLETE": "C. Potential case, minimum criteria incomplete: follow-up",
    "D_VALID_ICSR": "D. Valid ICSR, new or significant follow-up: case intake package",
}
ROOT_CAUSES = {
    "not_recognised": "Not recognised by channel staff",
    "not_forwarded": "Recognised but not forwarded",
    "not_received": "Forwarded but not received",
    "not_processed": "Received but not processed",
}
# Regulatory clock, as in runner/pvsweep_runner/rules.py (the app is deployed without the runner package).
SERIOUS_DAYS, NON_SERIOUS_DAYS, AT_RISK_SERIOUS, AT_RISK_NON_SERIOUS = 15, 90, 5, 15
CHECKLIST = [
    ("already_received", "Already received through another route? (safety database, intake queue, vendor log)"),
    ("adverse_event", "Is there an adverse event, and could the product have caused it? (solicited: reporter's or PV physician's assessment)"),
    ("minimum_criteria", "Are the four minimum criteria present? (patient, reporter, suspect product, suspected reaction)"),
    ("own_product", "Is it our product?"),
    ("seriousness", "Seriousness confirmed, including the IME list?"),
    ("dates", "Day 0 confirmed (new case) or receipt date of the significant follow-up information?"),
]


# ---- data access: Snowpark in Snowflake, DuckDB locally ------------------------------------------
class Data:
    def __init__(self):
        self.local = os.environ.get("PVSWEEP_LOCAL_DB")
        if self.local:
            import duckdb

            self.con = duckdb.connect(self.local)
            self.user = os.environ.get("USER", "local-reviewer")
            try:   # bring older local files up to date (tables, V009 columns, report views); idempotent
                from pvsweep_runner.store import ensure_local_schema

                ensure_local_schema(self.con)
            except ImportError:
                pass
        else:
            from snowflake.snowpark.context import get_active_session

            self.session = get_active_session()
            # Streamlit in Snowflake runs with owner's rights, where CURRENT_USER() is NULL; the viewer comes from st.user.
            self.user = None
            for attr in ("user", "experimental_user"):  # st.user first; the older name only as a fallback
                viewer = getattr(st, attr, None)
                try:
                    self.user = viewer.get("user_name") if viewer is not None else None
                except Exception:  # noqa: BLE001 - attribute shapes differ across Streamlit versions
                    self.user = None
                if self.user:
                    break
            self.user = self.user or self.session.sql("SELECT CURRENT_USER()").collect()[0][0]

    def df(self, sql: str, params: list | None = None) -> pd.DataFrame:
        if self.local:
            return self.con.execute(sql, params or []).df()
        df = self.session.sql(sql, params or []).to_pandas()
        df.columns = [c.lower() for c in df.columns]  # Snowflake returns upper-case names; the app uses lower-case
        return df

    def execute(self, sql: str, params: list | None = None) -> None:
        if self.local:
            self.con.execute(sql, params or [])
        else:
            self.session.sql(sql, params or []).collect()

    def variant(self) -> str:
        """Placeholder for a JSON parameter going into a VARIANT (Snowflake) or JSON (DuckDB) column; used with
        INSERT ... SELECT, which both accept."""
        return "?" if self.local else "PARSE_JSON(?)"

    def json_get(self, col: str, path: str) -> str:
        """Dialect-specific JSON field access."""
        if self.local:
            return f"json_extract_string({col}, '$.{path}')"
        return f"{col}:{path}::STRING"


@st.cache_resource
def data() -> Data:
    return Data()


D = data()
st.set_page_config(page_title="Pharmacovigilance Sweep", layout="wide")
st.title("Pharmacovigilance Sweep: review")

runs = D.df("SELECT run_id, provider, started_at, status, counts FROM SWEEP.RUN ORDER BY started_at DESC")
if runs.empty:
    st.info("No sweep runs yet.")
    st.stop()
run_id = st.sidebar.selectbox("Sweep run", runs["run_id"].tolist(),
                              format_func=lambda r: f"{r} ({runs.set_index('run_id').loc[r, 'provider']})")
page = st.sidebar.radio("Page", ["Review queue", "Reconciliation", "Channel KPIs", "Model comparison", "QC sample"])
st.sidebar.caption(f"Signed in as {D.user}")


def _json(v):
    """VARIANT/JSON columns arrive as text (DuckDB, Snowpark) or already parsed."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    return json.loads(v) if isinstance(v, str) else v


def finding_columns() -> set[str]:
    """SWEEP.FINDING gained summary, note and package in V009; older local files may not have them yet."""
    return set(D.df("SELECT * FROM SWEEP.FINDING WHERE 1 = 0").columns)


def findings_queue() -> pd.DataFrame:
    """The prioritised queue as the sweep wrote it (SWEEP.FINDING, priority first)."""
    cols = finding_columns()
    if not {"summary", "note", "package"} <= cols:
        return pd.DataFrame()
    j = D.json_get
    return D.df(f"""
        SELECT f.finding_id, f.record_id, f.finding_type, f.priority, f.summary, f.note,
               src.channel_code, src.channel_received_date,
               {j('f.package', 'match.outcome')} AS match_outcome,
               {j('f.package', 'dates.regulatory_status')} AS regulatory_status,
               {j('f.package', 'dates.days_remaining')} AS days_remaining,
               {j('f.package', 'forwarding.status')} AS forwarding_status,
               {j('f.package', 'suggested_outcome')} AS suggested_outcome,
               (SELECT count(*) FROM REVIEW.DECISION d WHERE d.finding_id = f.finding_id) AS decisions,
               f.package
        FROM SWEEP.FINDING f
        JOIN SRC.SOURCE_RECORD src ON src.record_id = f.record_id
        WHERE f.run_id = ?
        ORDER BY f.priority DESC, f.record_id""", [run_id])


def legacy_queue() -> pd.DataFrame:
    """Runs swept before the findings step have no SWEEP.FINDING rows: recompute the queue from the sweep tables."""
    return D.df("""
        SELECT s.record_id, src.channel_code, src.channel_received_date, src.country,
               s.screening_class, r.serious, r.ime_flag, r.regulatory_status, r.days_remaining, r.forwarding_status,
               r.causality_required, m.outcome AS match_outcome, m.confidence,
               (SELECT count(*) FROM REVIEW.DECISION d JOIN SWEEP.FINDING f ON f.finding_id = d.finding_id
                 WHERE f.record_id = s.record_id AND f.run_id = s.run_id) AS decisions
        FROM SWEEP.SCREENING s
        JOIN SRC.SOURCE_RECORD src ON src.record_id = s.record_id
        LEFT JOIN SWEEP.RULE_RESULT r ON r.run_id = s.run_id AND r.record_id = s.record_id
        LEFT JOIN SWEEP.MATCH_DECISION m ON m.run_id = s.run_id AND m.record_id = s.record_id
        WHERE s.run_id = ? AND s.screening_class IN ('ADVERSE_EVENT','SPECIAL_SITUATION','BLOCKED','INVALID')
        ORDER BY CASE WHEN r.serious THEN 0 ELSE 1 END,
                 CASE r.regulatory_status WHEN 'overdue' THEN 0 WHEN 'at_risk' THEN 1 ELSE 2 END,
                 r.days_remaining NULLS LAST""", [run_id])


def record_details(rid: str) -> None:
    rec = D.df("SELECT * FROM SRC.SOURCE_RECORD WHERE record_id = ?", [rid]).iloc[0]
    col1, col2 = st.columns([1, 1])
    with col1:
        st.markdown(f"**Record {rid}** · {rec['channel_code']} · {rec['channel_received_date']} · {rec['country']}")
        st.text_area("Source text", rec["record_text"], height=260, disabled=True)
        scr = D.df("SELECT screening_class, evidence, confidence FROM SWEEP.SCREENING WHERE run_id = ? AND record_id = ?", [run_id, rid])
        if not scr.empty:
            s0 = scr.iloc[0]
            st.markdown(f"**Screening:** {s0['screening_class']} (confidence {s0['confidence']})")
            st.caption("Evidence: " + "; ".join(_json(s0["evidence"]) or []))
    with col2:
        ext = D.df("SELECT result, valid, problems FROM SWEEP.EXTRACTION WHERE run_id = ? AND record_id = ?", [run_id, rid])
        if not ext.empty:
            st.markdown("**Extraction**")
            st.json(_json(ext.iloc[0]["result"]), expanded=False)
        rule = D.df("SELECT * FROM SWEEP.RULE_RESULT WHERE run_id = ? AND record_id = ?", [run_id, rid])
        if not rule.empty:
            st.markdown("**Rules**")
            st.dataframe(rule.drop(columns=["run_id", "record_id"]).T, use_container_width=True)
        m = D.df("SELECT outcome, matched_ids, justification, confidence, tool_calls FROM SWEEP.MATCH_DECISION WHERE run_id = ? AND record_id = ?", [run_id, rid])
        if not m.empty:
            mm = m.iloc[0]
            st.markdown(f"**Matching:** {mm['outcome']} (confidence {mm['confidence']}) · ids {mm['matched_ids']}")
            st.caption(mm["justification"] or "")
            with st.expander("Agent tool calls"):
                st.json(_json(mm["tool_calls"]))


def confirmed_package(package: dict, day0: dt.date, rationale: str, decision_id: str, today: dt.date) -> dict:
    """The case intake package as stored for outcome D: the sweep's proposal with the reviewer's confirmed day 0.
    Deadline, days remaining and status are recomputed from the confirmed day 0 at the decision date."""
    serious = bool(package.get("seriousness", {}).get("serious"))
    deadline = day0 + dt.timedelta(days=SERIOUS_DAYS if serious else NON_SERIOUS_DAYS)
    remaining = (deadline - today).days
    at_risk = AT_RISK_SERIOUS if serious else AT_RISK_NON_SERIOUS
    status = "overdue" if remaining < 0 else ("at_risk" if remaining <= at_risk else "on_time")
    dates = {**package.get("dates", {}), "confirmed_day0": day0.isoformat(), "regulatory_deadline": deadline.isoformat(), "days_remaining": remaining,
             "regulatory_status": status, "overdue": status == "overdue", "status_as_of": today.isoformat()}
    return {**package, "dates": dates, "late_submission": status == "overdue",
            "review": {"decision_id": decision_id, "reviewer": D.user, "confirmed_day0": day0.isoformat(),
                       "rationale": rationale}}


def decision_form(rid: str, finding_id: str | None, key: str, suggested: str | None = None,
                  package: dict | None = None) -> None:
    st.markdown("### Reviewer checklist")
    checks = {k: st.checkbox(label, key=f"{key}-{k}") for k, label in CHECKLIST}
    options = list(OUTCOMES)
    outcome = st.radio("Outcome", options, format_func=OUTCOMES.get, key=f"{key}-outcome",
                       index=options.index(suggested) if suggested in options else 0)
    day0 = root_cause = capa = None
    if outcome == "D_VALID_ICSR":
        proposed = (package or {}).get("dates", {}).get("proposed_day0")
        day0 = st.date_input("Confirmed day 0 (required for D)", value=dt.date.fromisoformat(proposed) if proposed else None,
                             key=f"{key}-day0")
        breach = bool((package or {}).get("compliance_note"))
        late = bool(package and day0 and confirmed_package(package, day0, "", "", dt.date.today())["late_submission"])
        if breach or late:
            kinds = " and ".join(k for k, on in (("forwarding breach", breach), ("late submission", late)) if on)
            st.caption(f"Compliance finding recorded with the decision: {kinds}.")
            root_cause = st.selectbox("Root cause", [None, *ROOT_CAUSES], key=f"{key}-root",
                                      format_func=lambda v: "to be determined" if v is None else ROOT_CAUSES[v])
            capa = st.text_input("Corrective and preventive action (optional)", key=f"{key}-capa") or None
    rationale = st.text_area("Rationale", key=f"{key}-rationale")
    if st.button("Record decision", type="primary", key=f"{key}-save"):
        if outcome == "D_VALID_ICSR" and day0 is None:
            st.error("Outcome D needs the confirmed day 0.")
            return
        if finding_id is None:   # legacy run without SWEEP.FINDING rows (local development only)
            finding = D.df("SELECT finding_id FROM SWEEP.FINDING WHERE run_id = ? AND record_id = ?", [run_id, rid])
            finding_id = finding.iloc[0]["finding_id"] if not finding.empty else f"F-{uuid.uuid4().hex[:10]}"
            if finding.empty:
                D.execute("INSERT INTO SWEEP.FINDING (run_id, finding_id, record_id, finding_type, priority) "
                          "VALUES (?, ?, ?, 'potential_case', 0)", [run_id, finding_id, rid])
        decision_id = f"D-{uuid.uuid4().hex[:10]}"
        D.execute("INSERT INTO REVIEW.DECISION (decision_id, finding_id, reviewer, outcome, checklist, confirmed_day0, rationale) "
                  f"SELECT ?, ?, ?, ?, {D.variant()}, ?, ?",
                  [decision_id, finding_id, D.user, outcome, json.dumps(checks), day0.isoformat() if day0 else None, rationale])
        written = [f"decision {decision_id}"]
        if outcome == "D_VALID_ICSR" and package:
            pkg = confirmed_package(package, day0, rationale, decision_id, dt.date.today())
            package_id = f"P-{uuid.uuid4().hex[:10]}"
            D.execute("INSERT INTO REVIEW.CASE_INTAKE_PACKAGE (package_id, finding_id, decision_id, initial_receipt_date, day0, "
                      f"regulatory_deadline, late_submission, package) SELECT ?, ?, ?, ?, ?, ?, ?, {D.variant()}",
                      [package_id, finding_id, decision_id, pkg["dates"].get("initial_receipt_date"), day0.isoformat(),
                       pkg["dates"]["regulatory_deadline"], pkg["late_submission"], json.dumps(pkg, sort_keys=True)])
            written.append(f"case intake package {package_id}")
            kinds = [k for k, on in (("forwarding_breach", pkg.get("compliance_note")),
                                     ("late_submission", pkg["late_submission"])) if on]
            for kind in kinds:
                compliance_id = f"CF-{uuid.uuid4().hex[:10]}"
                D.execute("INSERT INTO REVIEW.COMPLIANCE_FINDING (compliance_id, finding_id, kind, vendor_code, root_cause, capa) "
                          "SELECT ?, ?, ?, ?, ?, ?",
                          [compliance_id, finding_id, kind, pkg.get("record", {}).get("vendor_code"), root_cause, capa])
                written.append(f"compliance finding {compliance_id} ({kind})")
            if pkg["late_submission"]:
                st.error("Late submission: the regulatory deadline has passed. Open a deviation record.")
        elif outcome == "D_VALID_ICSR":
            st.warning("This finding has no case intake package (run swept before the findings step): only the decision "
                       "was recorded.")
        st.success(f"Decision {outcome} recorded for {finding_id} ({rid}) by {D.user} at "
                   f"{dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC: {', '.join(written)}")


def review_queue():
    q = findings_queue()
    if q.empty:
        st.warning("This run has no findings in SWEEP.FINDING (it was swept before the findings step): "
                   "showing the queue recomputed from the sweep tables.")
        q = legacy_queue()
        st.subheader(f"Prioritised queue (recomputed): {len(q)} records")
        st.dataframe(q, use_container_width=True, hide_index=True)
        if q.empty:
            return
        rid = st.selectbox("Open record", q["record_id"].tolist())
        record_details(rid)
        decision_form(rid, None, key=f"legacy-{rid}")
        return

    types = st.multiselect("Finding type", sorted(q["finding_type"].unique()), default=sorted(q["finding_type"].unique()))
    q = q[q["finding_type"].isin(types)]
    st.subheader(f"Prioritised queue: {len(q)} findings")
    st.dataframe(q.drop(columns=["package"]), use_container_width=True, hide_index=True)
    if q.empty:
        return
    labels = {r.finding_id: f"{r.priority:>5} · {r.finding_type} · {r.record_id} · {r.summary}" for r in q.itertuples()}
    fid = st.selectbox("Open finding", list(labels), format_func=labels.get)
    f = q.set_index("finding_id").loc[fid]
    package = _json(f["package"])
    st.markdown(f"**Finding {fid}** · {f['finding_type']} · priority {f['priority']}")
    if isinstance(f["note"], str) and f["note"]:
        st.warning(f["note"])
    if package:
        if package.get("compliance_note"):
            st.error(package["compliance_note"])
        if package.get("late_submission"):
            st.error("Regulatory deadline passed: late submission. Open a deviation record.")
        with st.expander("Proposed case intake package (day 0 and dates are proposals for the reviewer to confirm)",
                         expanded=True):
            st.json(package)
    record_details(f["record_id"])
    decision_form(f["record_id"], fid, key=fid, suggested=(package or {}).get("suggested_outcome"), package=package)


def reconciliation():
    st.subheader("Transmission reconciliation (deterministic)")
    st.dataframe(D.df("SELECT * FROM REPORT.RECONCILIATION_SUMMARY ORDER BY vendor_code"), hide_index=True)
    st.dataframe(D.df("SELECT * FROM REPORT.RECONCILIATION WHERE status <> 'received_as_sent' ORDER BY vendor_code, vendor_reference"),
                 use_container_width=True, hide_index=True)


def channel_kpis():
    st.subheader("Channel KPIs")
    st.dataframe(D.df("SELECT * FROM REPORT.CHANNEL_KPI WHERE run_id = ? ORDER BY channel_code", [run_id]), hide_index=True)


def model_comparison():
    st.subheader("Model comparison (audit trail)")
    st.dataframe(D.df("SELECT * FROM REPORT.MODEL_COMPARISON ORDER BY run_id, step, deployment"), hide_index=True)


def qc_sample():
    st.subheader("QC sample of records screened out")
    st.caption("Records classed as NO_PV_CONTENT are never closed silently: a deterministic sample (hash of the record id) "
               "is checked by a person. Open a sampled record from the review queue to record the QC decision.")
    if {"summary", "note", "package"} <= finding_columns():
        sample = D.df("""
            SELECT f.finding_id, f.record_id, src.channel_code, s.confidence, f.note,
                   (SELECT count(*) FROM REVIEW.DECISION d WHERE d.finding_id = f.finding_id) AS decisions, src.record_text
            FROM SWEEP.FINDING f
            JOIN SRC.SOURCE_RECORD src ON src.record_id = f.record_id
            LEFT JOIN SWEEP.SCREENING s ON s.run_id = f.run_id AND s.record_id = f.record_id
            WHERE f.run_id = ? AND f.finding_type = 'qc_sample' ORDER BY f.record_id""", [run_id])
        if not sample.empty:
            st.dataframe(sample, use_container_width=True, hide_index=True)
            return
        st.info("No qc_sample findings in this run (none of its screened-out records fell in the sample, or the run "
                "predates the findings step). Showing the lowest-confidence screened-out records instead.")
    st.dataframe(D.df("""
        SELECT s.record_id, src.channel_code, s.confidence, src.record_text
        FROM SWEEP.SCREENING s JOIN SRC.SOURCE_RECORD src ON src.record_id = s.record_id
        WHERE s.run_id = ? AND s.screening_class = 'NO_PV_CONTENT' ORDER BY s.confidence, s.record_id LIMIT 20""", [run_id]),
        use_container_width=True, hide_index=True)


{"Review queue": review_queue, "Reconciliation": reconciliation, "Channel KPIs": channel_kpis,
 "Model comparison": model_comparison, "QC sample": qc_sample}[page]()
