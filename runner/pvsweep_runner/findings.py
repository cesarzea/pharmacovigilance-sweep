"""Findings: what the reviewer works, built from the outputs of steps 1-4 (docs/architecture.md, section 6).

Pure functions over plain dicts, no database access, so the same record always gives the same finding,
priority and case intake package. The runner inserts the rows into SWEEP.FINDING.

- potential_case: a record routed to PV assessment that is not already known to PV (match outcome
  NO_MATCH, SIGNIFICANT_FOLLOW_UP, BLOCKED or not matched), plus records that could not be assessed
  (screening or extraction blocked, invalid or failed), so that nothing leaves the pipeline unseen.
- qc_sample: a deterministic share of a run's records screened out as NO_PV_CONTENT: the records are
  ranked by a hash of the record id and the first ceil(share x n) are taken, so a run with any record
  screened out always has at least one, and the same scope always gives the same sample.
- transmission_gap findings come from the reconciliation views, not from here.

Day 0 and the deadline in the package are proposals: the reviewer confirms day 0 before anything is
submitted.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import math
import json

ROUTED = ("ADVERSE_EVENT", "SPECIAL_SITUATION")
# Match outcomes meaning PV already holds the information: outcome B candidates, no finding of their own.
ALREADY_RECEIVED = ("IN_SAFETY_DB", "IN_INTAKE_QUEUE", "NON_SIGNIFICANT_FOLLOW_UP", "DUPLICATE_IN_SWEEP")
NOT_MATCHED = "not matched"
OWN_PRODUCT = ("own_brand", "substance_only")   # substance_only cannot be excluded as ours (definition section 6)
QC_SAMPLE_PERCENT = 5.0
PACKAGE_VERSION = "case-intake-package:v1"

# Priority weights (higher first). Seriousness dominates, then the regulatory clock, then compliance and
# causality, then the days remaining; definition section 6, step 5.
W_SERIOUS = 1000
W_IME = 200
W_HOSPITALISATION = 100
W_STATUS = {"overdue": 300, "at_risk": 150, "reviewer_sets_day0": 75, "on_time": 0, "clock_not_started": 0}
W_FORWARDING_BREACHED = 50
W_CAUSALITY_REQUIRED = 25
URGENCY_HORIZON = 60          # days_remaining at or beyond this adds nothing; each day closer adds one point
BLOCKED_DIVISOR = 2           # an agent that could not decide halves the score: a serious case stays above any
                              # non-serious one
UNASSESSED_PRIORITY = 500     # no extraction or rules: seriousness unknown, so between serious and non-serious
QC_PRIORITY = 0


def _iso(v):
    return v.isoformat() if isinstance(v, dt.date | dt.datetime) else v


def finding_id(run_id: str, record_id: str, finding_type: str) -> str:
    """Stable per run, record and type, so a resumed run cannot insert the same finding twice."""
    return "F-" + hashlib.sha256(f"{run_id}|{record_id}|{finding_type}".encode()).hexdigest()[:16]


def qc_rank(record_id: str) -> str:
    """Sort key for the QC sample: sha256 of the record id (never Python's salted hash()), stable across runs."""
    return hashlib.sha256(record_id.encode()).hexdigest()


def qc_sample(record_ids, percent: float = QC_SAMPLE_PERCENT) -> list[str]:
    """The run's QC sample: records screened out, ranked by hash, top ceil(percent % of n). At least one record
    whenever n > 0 and percent > 0."""
    ids = sorted(set(record_ids), key=lambda r: (qc_rank(r), r))
    if not ids or percent <= 0:
        return []
    k = min(len(ids), math.ceil(len(ids) * percent / 100 - 1e-9))
    return ids[:k]


def build_qc_findings(run_id: str, screened_out: list[dict], percent: float = QC_SAMPLE_PERCENT) -> list[dict]:
    """qc_sample finding rows for a run. screened_out: one dict per record screened out as NO_PV_CONTENT, with
    record_id and optionally channel_code and confidence."""
    by_id = {r["record_id"]: r for r in screened_out}
    rows = []
    for rid in qc_sample(by_id, percent):
        r = by_id[rid]
        rows.append({"finding_id": finding_id(run_id, rid, "qc_sample"), "record_id": rid, "finding_type": "qc_sample",
                     "priority": QC_PRIORITY,
                     "note": f"QC sample ({percent:g} %, at least one per run) of {len(by_id)} records screened out",
                     "summary": f"{r.get('channel_code')} · screened out (confidence {r.get('confidence') or '-'}) · QC sample",
                     "package": None})
    return rows


def hospitalised(extraction: dict | None) -> bool:
    if not extraction:
        return False
    return bool(extraction.get("seriousness", {}).get("hospitalisation")) or any(
        e.get("hospitalisation") for e in extraction.get("events", []))


def priority(rule: dict | None, extraction: dict | None = None, match_outcome: str | None = None) -> int:
    """Integer score, higher first. Without rule results (record not assessed) the score is fixed."""
    if rule is None:
        score = UNASSESSED_PRIORITY
    else:
        score = 0
        if rule.get("serious"):
            score += W_SERIOUS
        if rule.get("ime_flag"):
            score += W_IME
        if hospitalised(extraction):
            score += W_HOSPITALISATION
        score += W_STATUS.get(rule.get("regulatory_status") or "", 0)
        if rule.get("forwarding_status") == "breached":
            score += W_FORWARDING_BREACHED
        if rule.get("causality_required"):
            score += W_CAUSALITY_REQUIRED
        remaining = rule.get("days_remaining")
        if remaining is not None:
            score += max(0, min(URGENCY_HORIZON, URGENCY_HORIZON - int(remaining)))
    if match_outcome == "BLOCKED":
        score //= BLOCKED_DIVISOR
    return int(score)


def _seriousness_criteria(extraction: dict) -> list[str]:
    s = extraction.get("seriousness", {}) or {}
    return [k for k in ("death", "life_threatening", "hospitalisation", "disability", "congenital_anomaly",
                        "other_medically_important") if s.get(k)]


def _evidence(extraction: dict, screening_evidence: list[str] | None) -> list[str]:
    quotes: list[str] = []
    seen: set[str] = set()

    def add(q):
        if not q or not isinstance(q, str):
            return
        q = q.strip().strip('"\u201c\u201d').strip()   # models sometimes wrap spans in quotation marks
        key = " ".join(q.lower().split())
        if q and key not in seen:
            seen.add(key)
            quotes.append(q)

    for q in screening_evidence or []:
        add(q)
    add((extraction.get("patient") or {}).get("evidence"))
    add((extraction.get("reporter") or {}).get("evidence"))
    for p in extraction.get("products", []):
        add(p.get("evidence"))
    for e in extraction.get("events", []):
        add(e.get("evidence"))
    add((extraction.get("causality_statement") or {}).get("evidence"))
    return quotes


def compliance_note(rule: dict, record: dict, forwarding_timeline_days: int | None) -> str | None:
    if rule.get("forwarding_status") != "breached":
        return None
    timeline = f"{forwarding_timeline_days} business day(s)" if forwarding_timeline_days is not None else "the SDEA timeline"
    vendor = record.get("vendor_code") or record.get("channel_code")
    return (f"Forwarding timeline breached: {rule.get('forwarding_days')} business days from receipt in the channel on "
            f"{_iso(record.get('channel_received_date'))} to detection by the sweep, against {timeline} for {vendor}. "
            "Record a compliance finding (forwarding_breach) against the vendor or channel; this is not a late case.")


def suggested_outcome(rule: dict | None, match_outcome: str, extraction: dict | None = None) -> str | None:
    """Pre-filled reviewer outcome (definition section 7); the reviewer decides."""
    if rule is None or match_outcome == "BLOCKED" or rule.get("ownership") not in OWN_PRODUCT:
        return None
    ext = extraction or {}
    if (ext.get("event_context") or {}).get("planned_before_treatment") or (
            rule.get("report_type") == "solicited" and (ext.get("causality_statement") or {}).get("value") == "excluded"):
        return "A_NOT_REPORTABLE"   # procedure planned before treatment, or solicited event the reporter says is unrelated
    if not rule.get("criteria_complete"):
        return "C_INCOMPLETE"
    return "D_VALID_ICSR"


def build_package(record: dict, extraction: dict, rule: dict, decision: dict | None, *,
                  screening_class: str, screening_evidence: list[str] | None = None,
                  initial_receipt_date: dt.date | str | None = None,
                  forwarding_timeline_days: int | None = None, notes: list[str] | None = None) -> dict:
    """Case intake package for one potential case (definition section 7, outcome D).

    initial_receipt_date: the existing case's first receipt date for a significant follow-up (looked up by
    the caller); defaults to the record's channel receipt date for a new case."""
    outcome = (decision or {}).get("outcome") or NOT_MATCHED
    patient = extraction.get("patient") or {}
    reporter = extraction.get("reporter") or {}
    causality = extraction.get("causality_statement") or {}
    suspects, seen = [], set()
    for p in [p for p in extraction.get("products", []) if p.get("suspect", True)] or list(extraction.get("products", [])):
        key = ((p.get("name_verbatim") or "").strip().lower(), p.get("batch_lot"))
        if key not in seen:
            seen.add(key)
            suspects.append(p)
    status = rule.get("regulatory_status")
    day0_basis = {"SIGNIFICANT_FOLLOW_UP": "receipt of the significant follow-up information",
                  }.get(outcome, "first receipt of the minimum criteria by the MAH or its vendor")
    if status == "reviewer_sets_day0":
        day0_basis = "date the reviewer identified the event with the minimum criteria (social listening ODCS)"
    elif status == "clock_not_started":
        day0_basis = "not started: minimum criteria incomplete, follow-up needed"
    return {
        "package_version": PACKAGE_VERSION,
        "record": {"record_id": record["record_id"], "channel": record.get("channel_code"), "country": record.get("country"),
                   "vendor_code": record.get("vendor_code"), "vendor_reference": record.get("vendor_reference"),
                   "screening_class": screening_class},
        "product": {"name": suspects[0]["name_verbatim"] if suspects else None, "substance": rule.get("substance"),
                    "ownership": rule.get("ownership"),
                    "suspect_products": [{"name": p.get("name_verbatim"), "batch_lot": p.get("batch_lot")} for p in suspects]},
        "patient": {"sex": patient.get("sex"), "age_years": patient.get("age_years"), "initials": patient.get("initials")},
        "reporter": {"type": reporter.get("type"), "identifiable": reporter.get("identifiable")},
        "events": [{"verbatim": e.get("verbatim"), "proposed_term": e.get("proposed_term"),
                    "hospitalisation": bool(e.get("hospitalisation"))} for e in extraction.get("events", [])],
        "special_situations": list(extraction.get("special_situations", [])),
        "seriousness": {"serious": bool(rule.get("serious")), "ime": bool(rule.get("ime_flag")),
                        "criteria": _seriousness_criteria(extraction)},
        "causality": {"statement": causality.get("value", "not_stated"), "report_type": rule.get("report_type"),
                      "assessment_required": bool(rule.get("causality_required"))},
        "minimum_criteria": {"complete": bool(rule.get("criteria_complete")),
                             "missing_information": list(extraction.get("missing_information", []))},
        "event_context": extraction.get("event_context"),
        "dates": {
            "channel_received_date": _iso(record.get("channel_received_date")),
            "initial_receipt_date": _iso(initial_receipt_date or record.get("channel_received_date")),
            "onset_date": (extraction.get("dates") or {}).get("onset_date"),
            "proposed_day0": _iso(rule.get("proposed_day0")),
            "day0_basis": day0_basis,
            "regulatory_deadline": _iso(rule.get("regulatory_deadline")),
            "days_remaining": rule.get("days_remaining"),
            "regulatory_status": status,
            "overdue": status == "overdue",
        },
        "forwarding": {"days": rule.get("forwarding_days"), "status": rule.get("forwarding_status"),
                       "timeline_business_days": forwarding_timeline_days},
        "match": {"outcome": outcome, "matched_ids": list((decision or {}).get("matched_ids") or []),
                  "new_facts": list((decision or {}).get("new_facts") or []),
                  "confidence": (decision or {}).get("confidence"), "justification": (decision or {}).get("justification")},
        "evidence": _evidence(extraction, screening_evidence),
        "compliance_note": compliance_note(rule, record, forwarding_timeline_days),
        "late_submission": status == "overdue",
        "suggested_outcome": suggested_outcome(rule, outcome, extraction),
        "notes": list(notes or []),
    }


def _summary(record: dict, package: dict | None, outcome: str, note: str | None) -> str:
    if package is None:
        return f"{record.get('channel_code')} · not assessed · {note or outcome}"
    terms = ", ".join(e["proposed_term"] for e in package["events"] if e.get("proposed_term")) or \
        ", ".join(package["special_situations"]) or "no event"
    d = package["dates"]
    clock = d["regulatory_status"] or "-"
    if d["days_remaining"] is not None:
        clock += f" ({d['days_remaining']} d)"
    parts = [package["product"]["name"] or package["product"]["substance"] or "unknown product", terms,
             "serious" if package["seriousness"]["serious"] else "non-serious", clock, outcome]
    if package["forwarding"]["status"] == "breached":
        parts.append("forwarding breached")
    return " · ".join(str(p) for p in parts)


def build_findings(run_id: str, record: dict, screening_class: str, *, extraction: dict | None = None,
                   rule: dict | None = None, decision: dict | None = None, screening_evidence: list[str] | None = None,
                   screening_confidence: str | None = None, initial_receipt_date: dt.date | str | None = None,
                   forwarding_timeline_days: int | None = None, error: str | None = None) -> list[dict]:
    """potential_case rows for one processed record: zero or one row, with keys finding_id, record_id,
    finding_type, priority, summary, note and package (a dict, or None). Records screened out are sampled per
    run by build_qc_findings."""
    rid = record["record_id"]
    if screening_class == "NO_PV_CONTENT" and error is None:
        return []

    outcome = (decision or {}).get("outcome") or NOT_MATCHED
    if outcome in ALREADY_RECEIVED:
        return []

    notes: list[str] = []
    if error:
        notes.append(f"processing failed: {error}; assess manually")
    if screening_class in ("BLOCKED", "INVALID"):
        notes.append(f"screening {screening_class.lower()}: screen manually")
    elif extraction is None and not error:
        notes.append("extraction invalid: extract manually")
    if outcome == "BLOCKED":
        notes.append("matching blocked: check the safety database, intake queue and vendor log manually")
    if rule is not None and rule.get("ownership") not in OWN_PRODUCT:
        notes.append(f"product ownership '{rule.get('ownership')}': confirm it is our product before creating a case")
    if extraction is not None and rule is not None and not extraction.get("events") and not extraction.get("special_situations"):
        notes.append("no event or special situation extracted")

    package = None
    if extraction is not None and rule is not None:
        package = build_package(record, extraction, rule, decision, screening_class=screening_class,
                                screening_evidence=screening_evidence, initial_receipt_date=initial_receipt_date,
                                forwarding_timeline_days=forwarding_timeline_days, notes=notes)
        prio = priority(rule, extraction, outcome)
    else:
        prio = priority(None, None, outcome)
    note = "; ".join(notes) or None
    return [{"finding_id": finding_id(run_id, rid, "potential_case"), "record_id": rid, "finding_type": "potential_case",
             "priority": prio, "note": note, "summary": _summary(record, package, outcome, note), "package": package}]


def package_json(package: dict | None) -> str | None:
    """Canonical JSON for storage (sorted keys, so the same package always serialises the same way)."""
    return None if package is None else json.dumps(package, sort_keys=True, default=str, ensure_ascii=False)
