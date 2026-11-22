"""Step 4a: candidate retrieval with SQL blocking, before the agent looks at anything.

Blocking keys: substance, sex, age band (±3 years), event term, receipt-date window. A record with no
candidates still goes to the agent, which may widen the search with its tools; the baseline single
call only sees these candidates.
"""

from __future__ import annotations

import datetime as dt

DATE_WINDOW_DAYS = 180


def candidates(store, *, substance: str | None, sex: str | None, age: float | None, terms: list[str],
               channel_received: dt.date, vendor_code: str | None, vendor_reference: str | None,
               product_name: str | None, limit: int = 15) -> list[dict]:
    out: list[dict] = []
    if substance:
        age_lo, age_hi = (age - 3, age + 3) if age is not None else (None, None)
        rows = store.query(
            """
            SELECT c.case_id, c.initial_receipt_date, c.latest_receipt_date, c.age_years, c.sex, c.occurrence_country,
                   c.serious, c.hospitalisation, d.substance, e.pt
            FROM PV.SAFETY_CASE c
            JOIN (SELECT case_id, substance FROM PV.CASE_DRUG WHERE role IN ('primary_suspect','secondary_suspect')) d USING (case_id)
            JOIN PV.CASE_EVENT e USING (case_id)
            WHERE d.substance = ?
              AND (? IS NULL OR c.sex = ? OR c.sex = 'unknown')
              AND (? IS NULL OR c.age_years IS NULL OR c.age_years BETWEEN ? AND ?)
              AND c.latest_receipt_date BETWEEN ? AND ?
            ORDER BY (CASE WHEN lower(e.pt) IN ({terms}) THEN 0 ELSE 1 END), abs(c.latest_receipt_date - ?)
            LIMIT ?""".replace("{terms}", ",".join("?" * len(terms)) if terms else "''"),
            [substance, sex, sex, age, age_lo, age_hi,
             channel_received - dt.timedelta(days=DATE_WINDOW_DAYS), channel_received + dt.timedelta(days=30),
             *[t.lower() for t in terms], channel_received, limit],
        )
        seen = set()
        for r in rows:
            if r[0] in seen:
                continue
            seen.add(r[0])
            out.append({"source": "safety_db", "candidate_id": r[0],
                        "keys": {"substance": r[8], "sex": r[4], "age": r[3], "pt": r[9], "country": r[5],
                                 "initial_receipt_date": str(r[1]), "latest_receipt_date": str(r[2])}})
    if vendor_code and vendor_reference:
        for r in store.query("SELECT vendor_code, vendor_reference, sent_at, product_name, event_summary FROM PV.VENDOR_TX_LOG "
                             "WHERE vendor_code = ? AND vendor_reference = ?", [vendor_code, vendor_reference]):
            out.append({"source": "vendor_log", "candidate_id": f"{r[0]}/{r[1]}",
                        "keys": {"sent_at": str(r[2]), "product": r[3], "event": r[4]}})
    if product_name:
        for r in store.query("SELECT intake_id, channel_code, received_by_pv, status, summary FROM PV.INTAKE_QUEUE "
                             "WHERE lower(summary) LIKE ? AND received_by_pv BETWEEN ? AND ? LIMIT ?",
                             [f"%{product_name.lower()}%", channel_received - dt.timedelta(days=30),
                              channel_received + dt.timedelta(days=30), limit]):
            out.append({"source": "intake_queue", "candidate_id": r[0],
                        "keys": {"channel": r[1], "received_by_pv": str(r[2]), "status": r[3], "summary": r[4]}})
    return out
