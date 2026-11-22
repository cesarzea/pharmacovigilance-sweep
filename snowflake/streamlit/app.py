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
        else:
            from snowflake.snowpark.context import get_active_session

            self.session = get_active_session()
            # Streamlit in Snowflake runs with owner's rights, where CURRENT_USER() is NULL; the viewer comes from st.user.
            viewer = getattr(st, "user", None) or getattr(st, "experimental_user", None)
            self.user = (viewer.get("user_name") if viewer else None) or self.session.sql("SELECT CURRENT_USER()").collect()[0][0]

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


def review_queue():
    q = D.df("""
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
    st.subheader(f"Prioritised queue: {len(q)} findings")
    st.dataframe(q, use_container_width=True, hide_index=True)
    if q.empty:
        return
    rid = st.selectbox("Open finding", q["record_id"].tolist())
    rec = D.df("SELECT * FROM SRC.SOURCE_RECORD WHERE record_id = ?", [rid]).iloc[0]
    col1, col2 = st.columns([1, 1])
    with col1:
        st.markdown(f"**Record {rid}** · {rec['channel_code']} · {rec['channel_received_date']} · {rec['country']}")
        st.text_area("Source text", rec["record_text"], height=260, disabled=True)
        scr = D.df("SELECT screening_class, evidence, confidence FROM SWEEP.SCREENING WHERE run_id = ? AND record_id = ?", [run_id, rid]).iloc[0]
        st.markdown(f"**Screening:** {scr['screening_class']} (confidence {scr['confidence']})")
        ev = scr["evidence"]
        st.caption("Evidence: " + "; ".join(json.loads(ev) if isinstance(ev, str) else (ev or [])))
    with col2:
        ext = D.df("SELECT result, valid, problems FROM SWEEP.EXTRACTION WHERE run_id = ? AND record_id = ?", [run_id, rid])
        if not ext.empty:
            res = ext.iloc[0]["result"]
            st.markdown("**Extraction**")
            st.json(json.loads(res) if isinstance(res, str) else res, expanded=False)
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
                tc = mm["tool_calls"]
                st.json(json.loads(tc) if isinstance(tc, str) else tc)

    st.markdown("### Reviewer checklist")
    checks = {key: st.checkbox(label, key=f"{rid}-{key}") for key, label in CHECKLIST}
    outcome = st.radio("Outcome", list(OUTCOMES), format_func=OUTCOMES.get, key=f"{rid}-outcome")
    day0 = st.date_input("Confirmed day 0 (D only)", value=None, key=f"{rid}-day0") if outcome == "D_VALID_ICSR" else None
    rationale = st.text_area("Rationale", key=f"{rid}-rationale")
    if st.button("Record decision", type="primary", key=f"{rid}-save"):
        finding = D.df("SELECT finding_id FROM SWEEP.FINDING WHERE run_id = ? AND record_id = ?", [run_id, rid])
        finding_id = finding.iloc[0]["finding_id"] if not finding.empty else f"F-{uuid.uuid4().hex[:10]}"
        if finding.empty:
            D.execute("INSERT INTO SWEEP.FINDING (run_id, finding_id, record_id, finding_type, priority) VALUES (?, ?, ?, 'potential_case', 0)",
                      [run_id, finding_id, rid])
        D.execute("INSERT INTO REVIEW.DECISION (decision_id, finding_id, reviewer, outcome, checklist, confirmed_day0, rationale) "
                  "VALUES (?, ?, ?, ?, ?, ?, ?)",
                  [f"D-{uuid.uuid4().hex[:10]}", finding_id, D.user, outcome, json.dumps(checks), day0.isoformat() if day0 else None, rationale])
        st.success(f"Decision {outcome} recorded for {rid} by {D.user} at {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC")


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
    st.caption("Records classed as NO_PV_CONTENT are never closed silently: a sample is checked by a person.")
    st.dataframe(D.df("""
        SELECT s.record_id, src.channel_code, s.confidence, src.record_text
        FROM SWEEP.SCREENING s JOIN SRC.SOURCE_RECORD src ON src.record_id = s.record_id
        WHERE s.run_id = ? AND s.screening_class = 'NO_PV_CONTENT' ORDER BY s.confidence, s.record_id LIMIT 20""", [run_id]),
        use_container_width=True, hide_index=True)


{"Review queue": review_queue, "Reconciliation": reconciliation, "Channel KPIs": channel_kpis,
 "Model comparison": model_comparison, "QC sample": qc_sample}[page]()
