import datetime as dt

from pvsweep_runner import rules

PORTFOLIO = {"sertraline": "Sertavix", "escitalopram": "Escitrel", "duloxetine": "Duloxane", "venlafaxine": "Venlaris"}
IME = {"serotonin syndrome", "hyponatraemia", "arrhythmia"}


def extraction(**over):
    base = {
        "patient": {"initials": "AB", "age_years": 54, "sex": "female", "evidence": "AB, 54"},
        "reporter": {"type": "nurse", "name": "Zofia T.", "identifiable": True, "evidence": "Zofia T."},
        "products": [{"name_verbatim": "Escitrel", "suspect": True, "batch_lot": None, "evidence": "Escitrel"}],
        "events": [{"verbatim": "dizzy", "proposed_term": "Dizziness", "hospitalisation": False, "evidence": "dizzy"}],
        "special_situations": [],
        "seriousness": {"death": False, "life_threatening": False, "hospitalisation": False, "disability": False,
                        "congenital_anomaly": False, "other_medically_important": False},
        "causality_statement": {"value": "not_stated", "evidence": None},
        "event_context": {"reason_for_admission": None, "planned_before_treatment": False,
                          "follow_up_of_earlier_report": False, "new_information": None},
        "dates": {"onset_date": None, "record_date": None, "other_dates": []},
        "missing_information": [], "confidence": "high",
    }
    base.update(over)
    return base


def run(ext, **kw):
    args = dict(channel_report_type="solicited", is_social_odcs=False, channel_received=dt.date(2026, 10, 20),
                as_of=dt.date(2026, 10, 31), vendor_forwarding_business_days=1, pv_received=None,
                ime_terms=IME, portfolio=PORTFOLIO)
    args.update(kw)
    return rules.apply(ext, **args)


def test_non_serious_solicited_needs_causality_and_has_90_days():
    r = run(extraction())
    assert r.ownership == "own_brand" and r.substance == "escitalopram"
    assert r.causality_required is True
    assert r.serious is False
    assert r.proposed_day0 == dt.date(2026, 10, 20)
    assert r.regulatory_deadline == dt.date(2027, 1, 18)
    assert r.regulatory_status == "on_time"


def test_serious_by_ime_term_is_15_days_and_at_risk():
    r = run(extraction(events=[{"verbatim": "arrhythmia", "proposed_term": "Arrhythmia", "hospitalisation": False,
                                "evidence": "arrhythmia"}]))
    assert r.ime_flag and r.serious
    assert r.regulatory_deadline == dt.date(2026, 11, 4)
    assert r.days_remaining == 4 and r.regulatory_status == "at_risk"


def test_overdue_serious_case():
    r = run(extraction(seriousness={"death": False, "life_threatening": False, "hospitalisation": True, "disability": False,
                                    "congenital_anomaly": False, "other_medically_important": False}),
            channel_received=dt.date(2026, 9, 1))
    assert r.serious and r.regulatory_status == "overdue" and r.days_remaining < 0


def test_forwarding_breach_is_separate_from_regulatory_status():
    # received by the vendor on Monday 19 Oct, found by the sweep on Thursday 22 Oct: 3 business days > 1-day SDEA
    r = run(extraction(), channel_received=dt.date(2026, 10, 19), as_of=dt.date(2026, 10, 22))
    assert r.forwarding_days == 3 and r.forwarding_status == "breached"
    assert r.regulatory_status == "on_time"


def test_incomplete_criteria_do_not_start_the_clock():
    r = run(extraction(reporter={"type": "consumer", "name": None, "identifiable": False, "evidence": None}))
    assert r.criteria_complete is False
    assert r.proposed_day0 is None and r.regulatory_status == "clock_not_started"


def test_social_listening_leaves_day0_to_the_reviewer():
    r = run(extraction(), is_social_odcs=True, vendor_forwarding_business_days=2)
    assert r.regulatory_status == "reviewer_sets_day0" and r.proposed_day0 is None


def test_spontaneous_suspected_needs_no_causality_assessment():
    r = run(extraction(causality_statement={"value": "suspected", "evidence": "thinks it caused"}),
            channel_report_type="spontaneous", vendor_forwarding_business_days=None)
    assert r.causality_required is False and r.forwarding_status == "not_applicable"


def test_other_mah_product():
    r = run(extraction(products=[{"name_verbatim": "fluoxetine", "suspect": True, "batch_lot": None, "evidence": "fluoxetine"}]))
    assert r.ownership == "other" and r.substance is None


def test_substance_only_when_generic_named():
    r = run(extraction(products=[{"name_verbatim": "venlafaxine 75 mg", "suspect": True, "batch_lot": None, "evidence": "v"}]))
    assert r.ownership == "substance_only" and r.substance == "venlafaxine"


def test_business_days_skip_weekends():
    assert rules.business_days_between(dt.date(2026, 10, 16), dt.date(2026, 10, 19)) == 1  # Fri -> Mon
    assert rules.business_days_between(dt.date(2026, 10, 19), dt.date(2026, 10, 19)) == 0


def test_ownership_falls_back_to_non_suspect_product():
    # an admission nobody links to the medicine: the extractor marks the product as not suspect
    r = run(extraction(products=[{"name_verbatim": "Escitrel", "suspect": False, "batch_lot": None, "evidence": "Escitrel"}],
                       events=[{"verbatim": "admitted for a planned hernia repair", "proposed_term": "Hospitalisation",
                                "hospitalisation": True, "evidence": "admitted"}]))
    assert r.ownership == "own_brand" and r.substance == "escitalopram"
    assert r.criteria_complete is False  # no suspect product: the minimum criteria are not met


def test_ime_synonym_self_harm_ideation_is_serious():
    r = run(extraction(events=[{"verbatim": "thoughts of hurting himself", "proposed_term": "Self-harm ideation",
                                "hospitalisation": False, "evidence": "thoughts"}]),
            ime_terms=IME | {"self-harm ideation"})
    assert r.ime_flag and r.serious


def test_ime_token_overlap_qt_prolonged_is_serious():
    r = run(extraction(events=[{"verbatim": "QT prolonged on ECG", "proposed_term": "QT prolonged",
                                "hospitalisation": False, "evidence": "QT prolonged"}]),
            ime_terms=IME | {"electrocardiogram qt prolonged"})
    assert rules.is_ime_term("QT prolonged", {"electrocardiogram qt prolonged"})
    assert r.ime_flag and r.serious


def test_ime_lookup_ignores_case_and_spacing():
    assert rules.is_ime_term("  serotonin   SYNDROME ", IME)
    assert not rules.is_ime_term("Headache", IME)
