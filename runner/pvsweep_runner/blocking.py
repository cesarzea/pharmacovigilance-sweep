"""Step 4a: candidate retrieval with SQL blocking, before the agent looks at anything.

Two passes over the safety database, then the vendor log and the intake queue:

1. Exact-key pass: same substance, same sex (or unknown), age within ±1 year (or missing), and the
   case received between three weeks before and one week after the record. These are the cases the
   record most plausibly repeats, so they are always offered, whatever the event term says.
2. Ranked pass: substance, sex, age band (±3), a wider receipt-date window; the SQL returns up to 60
   rows and Python ranks them by a fuzzy event-term score (token overlap, so "Upper abdominal pain"
   ranks "Abdominal pain upper") and by date proximity.

The SQL stays simple and portable (DuckDB locally, Snowflake in the job). A record with no candidates
still goes to the agent, which may widen the search with its tools; the single-call baseline only sees
these candidates.
"""

from __future__ import annotations

import datetime as dt
import re

DATE_WINDOW_DAYS = 180
EXACT_BEFORE_DAYS = 21
EXACT_AFTER_DAYS = 7
TERM_HIT = 0.6
SQL_FETCH = 60

_TOKENS = re.compile(r"[a-z]+")


def term_score(a: str | None, b: str | None) -> float:
    """Token overlap between two term names: |intersection| / |tokens of the shorter|; 0..1."""
    ta, tb = set(_TOKENS.findall((a or "").lower())), set(_TOKENS.findall((b or "").lower()))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def best_term_score(pt: str | None, terms: list[str]) -> float:
    return max((term_score(pt, t) for t in terms), default=0.0)


_CASE_SQL = """
SELECT c.case_id, c.initial_receipt_date, c.latest_receipt_date, c.age_years, c.sex, c.occurrence_country,
       c.serious, c.hospitalisation, d.substance, e.pt
FROM PV.SAFETY_CASE c
JOIN (SELECT case_id, substance FROM PV.CASE_DRUG WHERE role IN ('primary_suspect','secondary_suspect')) d
  ON d.case_id = c.case_id
JOIN PV.CASE_EVENT e ON e.case_id = c.case_id
WHERE d.substance = ?
  AND (? IS NULL OR c.sex = ? OR c.sex = 'unknown')
  AND (? IS NULL OR c.age_years IS NULL OR c.age_years BETWEEN ? AND ?)
  AND c.latest_receipt_date BETWEEN ? AND ?
ORDER BY c.latest_receipt_date DESC, c.case_id
LIMIT ?"""


def _case_rows(store, substance: str, sex: str | None, age: float | None, age_slack: float,
               date_from: dt.date, date_to: dt.date, fetch: int) -> list[tuple]:
    age_lo, age_hi = (age - age_slack, age + age_slack) if age is not None else (None, None)
    return store.query(_CASE_SQL, [substance, sex, sex, age, age_lo, age_hi, date_from, date_to, fetch])


def _candidate(row: tuple, *, exact: bool, score: float) -> dict:
    return {"source": "safety_db", "candidate_id": row[0],
            "keys": {"substance": row[8], "sex": row[4], "age": row[3], "pt": row[9], "country": row[5],
                     "initial_receipt_date": str(row[1]), "latest_receipt_date": str(row[2])},
            "exact_key": exact, "term_score": round(score, 2)}


def candidates(store, *, substance: str | None, sex: str | None, age: float | None, terms: list[str],
               channel_received: dt.date, vendor_code: str | None, vendor_reference: str | None,
               product_name: str | None, limit: int = 15) -> list[dict]:
    out: list[dict] = []
    if substance:
        seen: set[str] = set()
        # One row per case: keep the best-scoring event term for each case id.
        best: dict[str, tuple[tuple, float]] = {}

        # Pass 1: exact keys, always offered.
        exact_rows = _case_rows(store, substance, sex, age, 1,
                                channel_received - dt.timedelta(days=EXACT_BEFORE_DAYS),
                                channel_received + dt.timedelta(days=EXACT_AFTER_DAYS), SQL_FETCH)
        for r in exact_rows:
            s = best_term_score(r[9], terms)
            if r[0] not in best or s > best[r[0]][1]:
                best[r[0]] = (r, s)
        exact_sorted = sorted(best.values(), key=lambda rs: (-rs[1], abs((rs[0][2] - channel_received).days)))
        for r, s in exact_sorted:
            if len(out) >= limit:
                break
            out.append(_candidate(r, exact=True, score=s))
            seen.add(r[0])

        # Pass 2: wider window, ranked by fuzzy term hit then date proximity.
        best = {}
        wide_rows = _case_rows(store, substance, sex, age, 3,
                               channel_received - dt.timedelta(days=DATE_WINDOW_DAYS),
                               channel_received + dt.timedelta(days=30), SQL_FETCH)
        for r in wide_rows:
            if r[0] in seen:
                continue
            s = best_term_score(r[9], terms)
            if r[0] not in best or s > best[r[0]][1]:
                best[r[0]] = (r, s)
        ranked = sorted(best.values(),
                        key=lambda rs: (0 if rs[1] >= TERM_HIT else 1, -rs[1], abs((rs[0][2] - channel_received).days)))
        for r, s in ranked:
            if len(out) >= limit:
                break
            out.append(_candidate(r, exact=False, score=s))
            seen.add(r[0])
    if vendor_code and vendor_reference:
        for r in store.query("SELECT vendor_code, vendor_reference, sent_at, product_name, event_summary FROM PV.VENDOR_TX_LOG "
                             "WHERE vendor_code = ? AND vendor_reference = ?", [vendor_code, vendor_reference]):
            out.append({"source": "vendor_log", "candidate_id": f"{r[0]}/{r[1]}",
                        "keys": {"sent_at": str(r[2]), "product": r[3], "event": r[4]}, "exact_key": True, "term_score": 1.0})
    if product_name:
        for r in store.query("SELECT intake_id, channel_code, received_by_pv, status, summary FROM PV.INTAKE_QUEUE "
                             "WHERE lower(summary) LIKE ? AND received_by_pv BETWEEN ? AND ? LIMIT ?",
                             [f"%{product_name.lower()}%", channel_received - dt.timedelta(days=30),
                              channel_received + dt.timedelta(days=30), limit]):
            out.append({"source": "intake_queue", "candidate_id": r[0],
                        "keys": {"channel": r[1], "received_by_pv": str(r[2]), "status": r[3], "summary": r[4]},
                        "exact_key": False, "term_score": round(best_term_score(r[4], terms), 2)})
    return out
