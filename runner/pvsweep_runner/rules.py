"""Step 3: deterministic rules on the extraction. No model involved.

Pure functions over plain dicts so they are unit-tested with fixtures (runner/tests/test_rules.py)
and give the same answer in the local backend and in Snowflake. Dates are proposals: the reviewer
confirms day 0 before anything is submitted (docs/architecture.md, section 6).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass

SERIOUS_DAYS = 15
NON_SERIOUS_DAYS = 90
AT_RISK_SERIOUS = 5
AT_RISK_NON_SERIOUS = 15


@dataclass
class RuleResult:
    ownership: str                 # own_brand | substance_only | other | none
    substance: str | None
    report_type: str               # spontaneous | solicited
    causality_required: bool
    ime_flag: bool
    serious: bool
    criteria_complete: bool
    proposed_day0: dt.date | None
    regulatory_deadline: dt.date | None
    days_remaining: int | None
    regulatory_status: str         # clock_not_started | reviewer_sets_day0 | on_time | at_risk | overdue | no_new_clock
    forwarding_days: int | None
    forwarding_status: str         # not_applicable | within_timeline | breached

    def as_dict(self) -> dict:
        return asdict(self)


def business_days_between(start: dt.date, end: dt.date) -> int:
    """Business days from start (exclusive) to end (inclusive); weekends excluded."""
    if end <= start:
        return 0
    days, d = 0, start
    while d < end:
        d += dt.timedelta(days=1)
        if d.weekday() < 5:
            days += 1
    return days


def product_ownership(products: list[dict], portfolio: dict[str, str]) -> tuple[str, str | None]:
    """portfolio maps substance -> brand. Ownership is decided by the suspect products; when the record
    names no suspect product (e.g. an admission nobody links to the medicine), the patient's own product
    still decides ownership, so the non-suspect products are used as a fallback."""
    brands = {b.lower(): s for s, b in portfolio.items()}
    suspect = [p for p in products if p.get("suspect", True)]
    candidates = suspect or list(products)
    best, substance = "none", None
    for p in candidates:
        name = p["name_verbatim"].strip().lower()
        if name in brands:
            return "own_brand", brands[name]
        for s in portfolio:
            if s in name:
                best, substance = "substance_only", s
        if best == "none":
            best = "other"
    return best, substance


def _normalise_term(term: str) -> str:
    return " ".join(term.lower().split())


def _tokens(term: str) -> set[str]:
    return {t for t in "".join(c if c.isalpha() else " " for c in term.lower()).split() if t}


def is_ime_term(term: str, ime_terms: set[str]) -> bool:
    """Exact match after normalisation, or a token overlap of at least 0.6 over the shorter token set, so
    that 'Self-harm ideation' matches 'Suicidal ideation' only through its listed synonym while
    'QT prolonged' matches 'Electrocardiogram QT prolonged'."""
    norm = _normalise_term(term)
    normalised = {_normalise_term(t) for t in ime_terms}
    if norm in normalised:
        return True
    toks = _tokens(term)
    if not toks:
        return False
    for t in normalised:
        other = _tokens(t)
        if not other:
            continue
        overlap = len(toks & other) / min(len(toks), len(other))
        if overlap >= 0.6:
            return True
    return False


def apply(extraction: dict, *, channel_report_type: str, is_social_odcs: bool, channel_received: dt.date,
          as_of: dt.date, vendor_forwarding_business_days: int | None, pv_received: dt.date | None,
          ime_terms: set[str], portfolio: dict[str, str]) -> RuleResult:
    ownership, substance = product_ownership(extraction.get("products", []), portfolio)

    events = extraction.get("events", [])
    terms = {e["proposed_term"] for e in events if e.get("proposed_term")}
    ime = any(is_ime_term(t, ime_terms) for t in terms)
    s = extraction.get("seriousness", {})
    serious = ime or any(s.get(k) for k in ("death", "life_threatening", "hospitalisation", "disability",
                                             "congenital_anomaly", "other_medically_important"))
    serious = serious or any(e.get("hospitalisation") for e in events)

    causality = extraction.get("causality_statement", {}).get("value", "not_stated")
    causality_required = channel_report_type == "solicited" and causality != "suspected"

    patient = extraction.get("patient", {})
    identifiable_patient = any(patient.get(k) not in (None, "unknown") for k in ("initials", "age_years", "sex"))
    identifiable_reporter = bool(extraction.get("reporter", {}).get("identifiable"))
    has_product = any(p.get("suspect", True) for p in extraction.get("products", []))
    has_event = bool(events) or bool(extraction.get("special_situations"))
    criteria_complete = identifiable_patient and identifiable_reporter and has_product and has_event

    # Day 0 proposal
    if not criteria_complete or not events:
        day0, deadline, remaining, status = None, None, None, "clock_not_started"
    elif is_social_odcs:
        day0, deadline, remaining, status = None, None, None, "reviewer_sets_day0"
    else:
        day0 = channel_received
        window = SERIOUS_DAYS if serious else NON_SERIOUS_DAYS
        deadline = day0 + dt.timedelta(days=window)
        remaining = (deadline - as_of).days
        at_risk = AT_RISK_SERIOUS if serious else AT_RISK_NON_SERIOUS
        status = "overdue" if remaining < 0 else ("at_risk" if remaining <= at_risk else "on_time")

    # Forwarding delay against the vendor's SDEA timeline
    if vendor_forwarding_business_days is None:
        fwd_days, fwd_status = None, "not_applicable"
    else:
        fwd_days = business_days_between(channel_received, pv_received or as_of)
        fwd_status = "breached" if fwd_days > vendor_forwarding_business_days else "within_timeline"

    return RuleResult(ownership, substance, channel_report_type, causality_required, ime, serious, criteria_complete,
                      day0, deadline, remaining, status, fwd_days, fwd_status)


# Match outcomes where PV already holds the information: no new regulatory clock (definition section 6).
NO_NEW_CLOCK_OUTCOMES = ("IN_SAFETY_DB", "IN_INTAKE_QUEUE", "NON_SIGNIFICANT_FOLLOW_UP", "DUPLICATE_IN_SWEEP")


def after_match(rule: dict, match_outcome: str | None) -> dict:
    """The rule result as stored: the clock is proposed before matching (and sent to the agent as such), then
    withdrawn when the agent finds that PV already holds the information. A new case or a significant
    follow-up keeps its clock; so does a record that was not matched or could not be matched."""
    if match_outcome not in NO_NEW_CLOCK_OUTCOMES:
        return dict(rule)
    return {**rule, "regulatory_status": "no_new_clock", "regulatory_deadline": None, "days_remaining": None}
