"""Ground truth first: build the scenario plan before any text exists.

Deterministic for a given seed. Anchors "already known" scenarios on real FAERS-derived cases from
data/stage/safety_case.parquet, so matching has something real to find. Produces:
- scenarios: one per source record, with every planted fact and the gold labels
- intake_queue, intake_log, vendor_tx_log, case_version: the PV-side records the scenarios imply
"""

from __future__ import annotations

import datetime as dt
import random
from dataclasses import asdict

import duckdb

from . import catalogue as C

BUSINESS_DAY = dt.timedelta(days=1)


def _weighted(rng: random.Random, pairs):
    items, weights = zip(*pairs, strict=True)
    return rng.choices(items, weights=weights, k=1)[0]


def _add_business_days(d: dt.date, n: int) -> dt.date:
    while n > 0:
        d += BUSINESS_DAY
        if d.weekday() < 5:
            n -= 1
    return d


def _initials(rng: random.Random) -> str:
    return rng.choice("ABCDEFGHJKLMNPRST") + rng.choice("ABCDEFGHJKLMNPRST")


def load_anchor_cases(stage_dir: str, n: int, rng: random.Random) -> list[dict]:
    con = duckdb.connect()
    rows = con.execute(f"""
        SELECT c.case_id, c.initial_receipt_date, c.latest_receipt_date, c.age_years, c.sex, c.occurrence_country,
               c.serious, c.hospitalisation, d.substance, d.product_name, e.pt
        FROM '{stage_dir}/safety_case.parquet' c
        JOIN (SELECT case_id, min(substance) substance, min(product_name) product_name
              FROM '{stage_dir}/case_drug.parquet' WHERE ownership = 'own_brand' AND role = 'primary_suspect'
              GROUP BY case_id) d USING (case_id)
        JOIN (SELECT case_id, min(pt) pt FROM '{stage_dir}/case_event.parquet' GROUP BY case_id) e USING (case_id)
        WHERE c.age_years BETWEEN 18 AND 85 AND c.sex IN ('female','male') AND c.initial_receipt_date IS NOT NULL
        ORDER BY hash(c.case_id)
        LIMIT {n * 3}""").fetchall()
    cols = ["case_id", "initial_receipt_date", "latest_receipt_date", "age_years", "sex", "country",
            "serious", "hospitalisation", "substance", "product_name", "pt"]
    cases = [dict(zip(cols, r, strict=True)) for r in rows]
    rng.shuffle(cases)
    return cases[:n]


def build(seed: int, total: int, stage_dir: str, brands: dict[str, str], reference_date: dt.date) -> dict:
    rng = random.Random(seed)
    kinds = [(k, k.weight) for k in C.KINDS]
    anchors = load_anchor_cases(stage_dir, total, rng)
    anchor_iter = iter(anchors)

    scenarios: list[C.Scenario] = []
    intake_queue, intake_log, vendor_tx_log, case_version = [], [], [], []
    seq = 0
    queue_seq = 0
    vendor_seq = {"PSPV": 0, "MIV": 0, "SOCV": 0}
    sweep_window_end = reference_date
    sweep_window_start = reference_date - dt.timedelta(days=120)

    for _ in range(total):
        kind = _weighted(rng, kinds)
        channel = _weighted(rng, [(c, C.CHANNEL_WEIGHTS[c]) for c in kind.channels])
        seq += 1
        record_id = f"{channel}-{seed:03d}-{seq:04d}"
        reporter_type = _weighted(rng, C.REPORTERS[channel])
        country = rng.choice(C.COUNTRIES)
        received = sweep_window_start + dt.timedelta(days=rng.randint(0, (sweep_window_end - sweep_window_start).days))
        ident_patient, ident_reporter = C.DEFAULT_IDENTIFIABLE[channel]

        s = C.Scenario(
            record_id=record_id, channel=channel, kind=kind.code, timing=None,
            substance=None, product_name=None, ownership="own_brand",
            reporter_type=reporter_type,
            reporter_name=None if channel == "SOCIAL" else f"{rng.choice(C.FIRST_NAMES)} {rng.choice('BDFGKLMNPRSTVW')}.",
            patient_initials=_initials(rng), patient_age=rng.randint(19, 82), patient_sex=rng.choice(["female", "male"]),
            country=country, event_pt=None, event_context=None, serious=False, hospitalisation=False,
            causality_statement="not_stated", special_situation=None, onset_date=None,
            channel_received_date=received.isoformat(), vendor_sent_date=None, pv_received_date=None,
            anchor_case_id=None, anchor_intake_id=None,
            identifiable_patient=ident_patient, identifiable_reporter=ident_reporter,
            gold_screening=kind.screening, gold_match=kind.match, gold_outcome=kind.outcome,
        )

        # product
        if kind.code == "OTHER_MAH_PRODUCT":
            s.substance = rng.choice(C.OTHER_MAH_PRODUCTS)
            s.product_name = s.substance
            s.ownership = "other"
        else:
            s.substance = rng.choice(C.SUBSTANCES)
            s.product_name = brands[s.substance] if rng.random() < 0.6 else s.substance
            s.ownership = "own_brand" if s.product_name == brands[s.substance] else "substance_only"

        # event / topic
        if kind.has_event:
            pt, serious, hosp, context = rng.choice(C.EVENTS)
            s.event_pt, s.serious, s.hospitalisation, s.event_context = pt, serious, hosp, context
            onset = received - dt.timedelta(days=rng.randint(1, 40))
            s.onset_date = onset.isoformat()
        if kind.code == "PLANNED_PROCEDURE":
            s.event_pt, s.serious, s.hospitalisation = "Hospitalisation", True, True
            s.event_context = f"admitted for a {rng.choice(C.PLANNED_PROCEDURES)}, unrelated to the medicine"
        if kind.code == "SPECIAL_SITUATION":
            s.special_situation, s.event_context = rng.choice(C.SPECIAL_SITUATIONS)
        if kind.code == "NO_PV_CONTENT":
            s.topic = rng.choice(C.NO_PV_TOPICS)
            s.patient_initials, s.patient_age, s.patient_sex = None, None, None
        if kind.code in ("NEW_SPONTANEOUS", "NEW_PSP_WITH_CAUSALITY", "IN_SAFETY_DB", "SIGNIFICANT_FOLLOW_UP"):
            s.causality_statement = "suspected"
        if kind.code == "NEW_SPONTANEOUS_EXCLUDED":
            s.causality_statement = "excluded"
        if kind.code == "INCOMPLETE":
            if channel == "SOCIAL" or rng.random() < 0.5:
                s.identifiable_reporter = False
            else:
                s.identifiable_patient = False
                s.patient_initials, s.patient_age, s.patient_sex = None, None, None

        # anchors on real cases
        if kind.needs_case:
            a = next(anchor_iter, None)
            if a is None:
                continue
            s.anchor_case_id = a["case_id"]
            s.substance, s.product_name, s.ownership = a["substance"], a["product_name"], "own_brand"
            s.patient_age, s.patient_sex, s.country = int(a["age_years"]), a["sex"], a["country"]
            s.event_pt = a["pt"]
            s.serious, s.hospitalisation = bool(a["serious"]), bool(a["hospitalisation"])
            known = {e[0]: e[3] for e in C.EVENTS}
            s.event_context = known.get(a["pt"], f"the patient developed {a['pt'].lower()}")
            first = a["initial_receipt_date"]
            # the channel record is written shortly after the safety case was received, so dates agree
            received = a["latest_receipt_date"] + dt.timedelta(days=rng.randint(0, 14))
            s.channel_received_date = received.isoformat()
            s.onset_date = (a["latest_receipt_date"] - dt.timedelta(days=rng.randint(1, 30))).isoformat()
            case_version.append({"case_id": a["case_id"], "case_version": 1, "received_date": first.isoformat(),
                                 "significant": True, "information_summary": f"Initial report: {a['pt']}"})
            if kind.code == "SIGNIFICANT_FOLLOW_UP":
                pt, _, _, context = rng.choice([e for e in C.EVENTS if e[2]])  # a hospitalisation
                s.extra_facts["new_information"] = f"{pt}: {context}"
                s.serious, s.hospitalisation = True, True
            elif kind.code == "NON_SIGNIFICANT_FOLLOW_UP":
                s.extra_facts["repeats"] = "same event, no new facts"

        if kind.needs_queue:
            queue_seq += 1
            intake_id = f"INT-{queue_seq:05d}"
            s.anchor_intake_id = intake_id
            pv_received = received + dt.timedelta(days=rng.randint(0, 2))
            intake_queue.append({"intake_id": intake_id, "channel_code": channel, "vendor_reference": None,
                                 "received_by_pv": pv_received.isoformat() + "T10:00:00", "status": "pending",
                                 "case_id": None,
                                 "summary": f"{s.product_name}: {s.event_pt}, {s.patient_sex} {s.patient_age}y, {country}"})

        # timing and vendor forwarding for records that should have reached PV
        vendor = C.REPORTERS and {"PSP": "PSPV", "MI": "MIV", "SOCIAL": "SOCV"}.get(channel)
        if kind.match == "NO_MATCH" and kind.outcome in ("D_VALID_ICSR", "C_INCOMPLETE"):
            s.timing = _weighted(rng, C.TIMING)
            if s.timing == "OVERDUE":
                # push receipt back so the regulatory clock has expired by the reference date
                received = reference_date - dt.timedelta(days=(20 if s.serious else 100) + rng.randint(0, 20))
                s.channel_received_date = received.isoformat()
                s.onset_date = (received - dt.timedelta(days=rng.randint(1, 20))).isoformat()
        if vendor and kind.code != "NO_PV_CONTENT":
            vendor_seq[vendor] += 1
            ref = f"{vendor}-{vendor_seq[vendor]:05d}"
            s.extra_facts["vendor_reference"] = ref
            timeline = {"PSPV": 1, "MIV": 1, "SOCV": 2}[vendor]
            if kind.match in ("IN_SAFETY_DB", "IN_INTAKE_QUEUE", "SIGNIFICANT_FOLLOW_UP", "NON_SIGNIFICANT_FOLLOW_UP"):
                sent = _add_business_days(received, rng.randint(0, timeline))
                s.vendor_sent_date = sent.isoformat()
                vendor_tx_log.append({"vendor_code": vendor, "vendor_reference": ref, "sent_at": sent.isoformat() + "T16:00:00",
                                      "product_name": s.product_name, "event_summary": s.event_pt})
                intake_log.append({"intake_id": f"INT-LOG-{len(intake_log) + 1:05d}", "vendor_code": vendor,
                                   "vendor_reference": ref, "received_by_pv": sent.isoformat() + "T16:05:00",
                                   "product_name": s.product_name, "event_summary": s.event_pt})
            elif s.timing == "FORWARDING_BREACHED":
                # vendor logged it as sent, PV never received it (transmission gap)
                sent = _add_business_days(received, timeline + rng.randint(2, 6))
                s.vendor_sent_date = sent.isoformat()
                vendor_tx_log.append({"vendor_code": vendor, "vendor_reference": ref, "sent_at": sent.isoformat() + "T16:00:00",
                                      "product_name": s.product_name, "event_summary": s.event_pt})

        # gold day 0: first date the MAH or its vendor held the minimum criteria
        if kind.outcome == "D_VALID_ICSR":
            if kind.code == "SIGNIFICANT_FOLLOW_UP":
                s.gold_day0 = s.channel_received_date
            elif channel == "SOCIAL":
                s.gold_day0 = None  # the reviewer's identification date; set at review
            else:
                s.gold_day0 = s.channel_received_date
        scenarios.append(s)

    return {
        "seed": seed, "reference_date": reference_date.isoformat(),
        "scenarios": [asdict(s) for s in scenarios],
        "intake_queue": intake_queue, "intake_log": intake_log,
        "vendor_tx_log": vendor_tx_log, "case_version": case_version,
    }
