import datetime as dt
import json

from pvsweep_runner import findings as F

RUN = "run-test"


def rule(**over):
    base = {"ownership": "own_brand", "substance": "sertraline", "report_type": "solicited", "causality_required": False,
            "ime_flag": False, "serious": False, "criteria_complete": True, "proposed_day0": dt.date(2026, 10, 20),
            "regulatory_deadline": dt.date(2027, 1, 18), "days_remaining": 79, "regulatory_status": "on_time",
            "forwarding_days": 1, "forwarding_status": "within_timeline"}
    base.update(over)
    return base


def extraction(**over):
    base = {
        "patient": {"initials": "MK", "age_years": 67, "sex": "female", "evidence": "Mrs MK, 67"},
        "reporter": {"type": "nurse", "name": "Nurse Ana P.", "identifiable": True, "evidence": "Nurse Ana P."},
        "products": [{"name_verbatim": "Sertavix", "suspect": True, "batch_lot": "L123", "evidence": "on Sertavix 50 mg"}],
        "events": [{"verbatim": "low sodium, admitted", "proposed_term": "Hyponatraemia", "hospitalisation": True,
                    "evidence": "admitted with low sodium"}],
        "special_situations": [],
        "seriousness": {"death": False, "life_threatening": False, "hospitalisation": True, "disability": False,
                        "congenital_anomaly": False, "other_medically_important": False},
        "causality_statement": {"value": "suspected", "evidence": "the nurse thinks Sertavix caused it"},
        "event_context": {"reason_for_admission": "hyponatraemia", "planned_before_treatment": False,
                          "follow_up_of_earlier_report": False, "new_information": None},
        "dates": {"onset_date": "2026-10-15", "record_date": "2026-10-20", "other_dates": []},
        "missing_information": ["outcome"], "confidence": "high",
    }
    base.update(over)
    return base


RECORD = {"record_id": "PSP-0042", "channel_code": "PSP", "channel_received_date": dt.date(2026, 10, 20), "country": "SE",
          "vendor_code": "PSPV", "vendor_reference": "PSPV-7781", "record_text": "..."}


# ---- priority ---------------------------------------------------------------------------------------
def test_serious_outranks_any_non_serious():
    worst_non_serious = rule(regulatory_status="overdue", days_remaining=-30, forwarding_status="breached",
                             causality_required=True)
    mild_serious = rule(serious=True, regulatory_status="on_time", days_remaining=14)
    assert F.priority(mild_serious) > F.priority(worst_non_serious)


def test_ime_and_hospitalisation_raise_priority():
    base = rule(serious=True, days_remaining=10)
    assert F.priority(rule(serious=True, ime_flag=True, days_remaining=10)) > F.priority(base)
    assert F.priority(base, extraction()) > F.priority(base, extraction(events=[], seriousness={}))


def test_regulatory_status_order_overdue_at_risk_on_time():
    overdue = F.priority(rule(serious=True, regulatory_status="overdue", days_remaining=-1))
    at_risk = F.priority(rule(serious=True, regulatory_status="at_risk", days_remaining=3))
    on_time = F.priority(rule(serious=True, regulatory_status="on_time", days_remaining=12))
    assert overdue > at_risk > on_time


def test_breach_causality_and_fewer_days_raise_priority():
    base = rule(days_remaining=40)
    assert F.priority(rule(days_remaining=40, forwarding_status="breached")) > F.priority(base)
    assert F.priority(rule(days_remaining=40, causality_required=True)) > F.priority(base)
    assert F.priority(rule(days_remaining=20)) > F.priority(base)
    assert F.priority(rule(days_remaining=200)) == F.priority(rule(days_remaining=60))  # beyond the horizon


def test_blocked_is_lower_but_serious_blocked_stays_above_non_serious():
    serious = rule(serious=True, regulatory_status="at_risk", days_remaining=3)
    assert F.priority(serious, match_outcome="BLOCKED") < F.priority(serious, match_outcome="NO_MATCH")
    worst_non_serious = rule(regulatory_status="overdue", days_remaining=-30, forwarding_status="breached",
                             causality_required=True)
    assert F.priority(rule(serious=True, days_remaining=14), match_outcome="BLOCKED") > F.priority(worst_non_serious)


def test_findings_sort_by_priority():
    recs = [("A", rule(serious=True, regulatory_status="overdue", days_remaining=-2), "NO_MATCH"),
            ("B", rule(), "NO_MATCH"),
            ("C", rule(serious=True, regulatory_status="at_risk", days_remaining=4), "SIGNIFICANT_FOLLOW_UP"),
            ("D", rule(serious=True, regulatory_status="overdue", days_remaining=-2), "BLOCKED")]
    rows = []
    for rid, r, outcome in recs:
        rows += F.build_findings(RUN, {**RECORD, "record_id": rid}, "ADVERSE_EVENT", extraction=extraction(), rule=r,
                                 decision={"outcome": outcome, "matched_ids": ["C-1"] if outcome != "NO_MATCH" else []})
    order = [f["record_id"] for f in sorted(rows, key=lambda f: -f["priority"])]
    assert order == ["A", "C", "D", "B"]


# ---- which records become findings --------------------------------------------------------------------
def test_already_received_outcomes_give_no_finding():
    for outcome in F.ALREADY_RECEIVED:
        assert F.build_findings(RUN, RECORD, "ADVERSE_EVENT", extraction=extraction(), rule=rule(),
                                decision={"outcome": outcome, "matched_ids": ["X"]}) == []


def test_not_matched_is_still_a_potential_case():
    [f] = F.build_findings(RUN, RECORD, "ADVERSE_EVENT", extraction=extraction(), rule=rule(), decision=None)
    assert f["finding_type"] == "potential_case"
    assert f["package"]["match"]["outcome"] == F.NOT_MATCHED


def test_unassessed_records_are_not_lost():
    [f] = F.build_findings(RUN, RECORD, "INVALID")
    assert f["finding_type"] == "potential_case" and f["package"] is None
    assert f["priority"] == F.UNASSESSED_PRIORITY and "screen manually" in f["note"]
    [g] = F.build_findings(RUN, RECORD, "ADVERSE_EVENT")   # extraction invalid
    assert "extraction invalid" in g["note"]


def test_blocked_match_gets_a_note():
    [f] = F.build_findings(RUN, RECORD, "ADVERSE_EVENT", extraction=extraction(), rule=rule(serious=True),
                           decision={"outcome": "BLOCKED", "matched_ids": []})
    assert "matching blocked" in f["note"]
    assert f["package"]["suggested_outcome"] is None


# ---- QC sample ------------------------------------------------------------------------------------------
def test_qc_sample_takes_top_five_percent_rounded_up_by_hash():
    ids = [f"MI-{i:05d}" for i in range(20000)]
    sample = F.qc_sample(ids)
    assert len(sample) == 1000
    assert sample == F.qc_sample(list(reversed(ids)))                 # order of input does not matter
    assert sample == sorted(ids, key=F.qc_rank)[:1000]
    assert len(F.qc_sample(ids[:73])) == 4                             # ceil(3.65)
    assert len(F.qc_sample(ids[:1])) == 1 and len(F.qc_sample(ids[:20])) == 1 and len(F.qc_sample(ids[:21])) == 2
    assert F.qc_sample([]) == [] and F.qc_sample(ids[:10], percent=0) == []
    assert F.qc_sample(ids[:10], percent=100) == sorted(ids[:10], key=F.qc_rank)


def test_qc_sample_is_stable_across_runs_and_scopes():
    ids = [f"CRM-{i:04d}" for i in range(200)]
    small = F.qc_sample(ids)
    assert small == F.qc_sample(ids)
    # every sampled record ranks before every record left out, so the sample does not depend on input order
    assert max(F.qc_rank(r) for r in small) < min(F.qc_rank(r) for r in set(ids) - set(small))


def test_qc_findings_rows():
    out = [{"record_id": f"CRM-{i:04d}", "channel_code": "CRM", "confidence": "high"} for i in range(30)]
    rows = F.build_qc_findings(RUN, out)
    assert len(rows) == 2
    for f in rows:
        assert f["finding_type"] == "qc_sample" and f["package"] is None and f["priority"] == F.QC_PRIORITY
        assert f["finding_id"] == F.finding_id(RUN, f["record_id"], "qc_sample")
        assert "screened out (confidence high)" in f["summary"]
    assert F.build_findings(RUN, RECORD, "NO_PV_CONTENT") == []      # per-record builder leaves sampling to the run


# ---- case intake package ---------------------------------------------------------------------------------
def test_full_package_for_a_significant_follow_up_with_forwarding_breach():
    r = rule(serious=True, regulatory_status="at_risk", days_remaining=4, regulatory_deadline=dt.date(2026, 11, 4),
             forwarding_days=8, forwarding_status="breached")
    decision = {"outcome": "SIGNIFICANT_FOLLOW_UP", "matched_ids": ["CASE-001"], "new_facts": ["hospitalised"],
                "confidence": "high", "justification": "same patient, new admission", "tool_calls": [{"x": 1}]}
    [f] = F.build_findings(RUN, RECORD, "ADVERSE_EVENT", extraction=extraction(), rule=r, decision=decision,
                           screening_evidence=["admitted with low sodium"], initial_receipt_date=dt.date(2026, 3, 2),
                           forwarding_timeline_days=1)
    assert f["finding_id"] == F.finding_id(RUN, "PSP-0042", "potential_case")
    assert f["priority"] == F.W_SERIOUS + F.W_HOSPITALISATION + F.W_STATUS["at_risk"] + F.W_FORWARDING_BREACHED + 56
    p = f["package"]
    assert p["record"] == {"record_id": "PSP-0042", "channel": "PSP", "country": "SE", "vendor_code": "PSPV",
                           "vendor_reference": "PSPV-7781", "screening_class": "ADVERSE_EVENT"}
    assert p["product"] == {"name": "Sertavix", "substance": "sertraline", "ownership": "own_brand",
                            "suspect_products": [{"name": "Sertavix", "batch_lot": "L123"}]}
    assert p["patient"] == {"sex": "female", "age_years": 67, "initials": "MK"}
    assert p["reporter"] == {"type": "nurse", "identifiable": True}
    assert p["events"] == [{"verbatim": "low sodium, admitted", "proposed_term": "Hyponatraemia", "hospitalisation": True}]
    assert p["seriousness"] == {"serious": True, "ime": False, "criteria": ["hospitalisation"]}
    assert p["causality"] == {"statement": "suspected", "report_type": "solicited", "assessment_required": False}
    assert p["minimum_criteria"] == {"complete": True, "missing_information": ["outcome"]}
    assert p["dates"] == {"channel_received_date": "2026-10-20", "initial_receipt_date": "2026-03-02",
                          "onset_date": "2026-10-15", "proposed_day0": "2026-10-20",
                          "day0_basis": "receipt of the significant follow-up information",
                          "regulatory_deadline": "2026-11-04", "days_remaining": 4, "regulatory_status": "at_risk",
                          "overdue": False}
    assert p["forwarding"] == {"days": 8, "status": "breached", "timeline_business_days": 1}
    assert p["match"] == {"outcome": "SIGNIFICANT_FOLLOW_UP", "matched_ids": ["CASE-001"], "new_facts": ["hospitalised"],
                          "confidence": "high", "justification": "same patient, new admission"}
    assert p["evidence"][0] == "admitted with low sodium"
    assert "on Sertavix 50 mg" in p["evidence"] and p["evidence"].count("admitted with low sodium") == 1
    assert "breached" in p["compliance_note"] and "not a late case" in p["compliance_note"]
    assert p["late_submission"] is False and p["suggested_outcome"] == "D_VALID_ICSR"
    assert "Nurse Ana P." not in json.dumps({k: v for k, v in p.items() if k != "evidence"})   # reporter name stays out
    assert F.package_json(p) == F.package_json(json.loads(F.package_json(p)))   # JSON-safe and canonical
    assert "forwarding breached" in f["summary"] and "SIGNIFICANT_FOLLOW_UP" in f["summary"]


def test_new_case_package_defaults_and_overdue_flag():
    r = rule(serious=True, regulatory_status="overdue", days_remaining=-3, forwarding_status="within_timeline")
    [f] = F.build_findings(RUN, RECORD, "ADVERSE_EVENT", extraction=extraction(), rule=r,
                           decision={"outcome": "NO_MATCH", "matched_ids": []})
    d = f["package"]["dates"]
    assert d["initial_receipt_date"] == "2026-10-20" and d["overdue"] is True
    assert f["package"]["late_submission"] is True and f["package"]["compliance_note"] is None


def test_incomplete_criteria_suggest_follow_up():
    r = rule(criteria_complete=False, proposed_day0=None, regulatory_deadline=None, days_remaining=None,
             regulatory_status="clock_not_started")
    [f] = F.build_findings(RUN, RECORD, "ADVERSE_EVENT", extraction=extraction(), rule=r, decision=None)
    assert f["package"]["suggested_outcome"] == "C_INCOMPLETE"
    assert f["package"]["dates"]["day0_basis"].startswith("not started")


def test_package_deduplicates_evidence_and_products():
    ext = extraction(products=[{"name_verbatim": "Sertavix", "suspect": True, "batch_lot": None, "evidence": "Sertavix"},
                               {"name_verbatim": "sertavix", "suspect": True, "batch_lot": None, "evidence": "Sertavix"}])
    [f] = F.build_findings(RUN, RECORD, "ADVERSE_EVENT", extraction=ext, rule=rule(), decision=None,
                           screening_evidence=['"admitted with low sodium"', "Sertavix"])
    p = f["package"]
    assert len(p["product"]["suspect_products"]) == 1
    assert p["evidence"].count("admitted with low sodium") == 1 and p["evidence"].count("Sertavix") == 1


def test_other_mah_product_gets_a_note_and_no_suggested_outcome():
    [f] = F.build_findings(RUN, RECORD, "ADVERSE_EVENT", extraction=extraction(), rule=rule(ownership="other", substance=None),
                           decision={"outcome": "NO_MATCH", "matched_ids": []})
    assert "ownership 'other'" in f["note"] and f["package"]["suggested_outcome"] is None
    [g] = F.build_findings(RUN, RECORD, "ADVERSE_EVENT", extraction=extraction(), rule=rule(ownership="substance_only"),
                           decision=None)
    assert g["note"] is None and g["package"]["suggested_outcome"] == "D_VALID_ICSR"


def test_section7_outcome_a_triggers_are_suggested():
    planned = extraction(event_context={"reason_for_admission": "knee replacement", "planned_before_treatment": True,
                                        "follow_up_of_earlier_report": False, "new_information": None})
    [f] = F.build_findings(RUN, RECORD, "ADVERSE_EVENT", extraction=planned, rule=rule(), decision=None)
    assert f["package"]["suggested_outcome"] == "A_NOT_REPORTABLE"
    excluded = extraction(causality_statement={"value": "excluded", "evidence": "not related to Sertavix"})
    [g] = F.build_findings(RUN, RECORD, "ADVERSE_EVENT", extraction=excluded, rule=rule(report_type="solicited"), decision=None)
    assert g["package"]["suggested_outcome"] == "A_NOT_REPORTABLE"
    [h] = F.build_findings(RUN, RECORD, "ADVERSE_EVENT", extraction=excluded, rule=rule(report_type="spontaneous"),
                           decision=None)
    assert h["package"]["suggested_outcome"] == "D_VALID_ICSR"   # spontaneous: PV records the exclusion, still a case
