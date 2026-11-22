# Matching analysis: run `run-eb48984348d0` (GPT, 225 records, agent in-process)

Source: `data/local/analysis-copy.duckdb` (read-only copy of the local backend), `data/synthetic/plan.json`.
188 records reached matching; 151 agreed with the gold label (0.803); 37 disagreed. Rules: 23 seriousness
and 3 ownership disagreements.

## 1. Disagreements by cause

| Cause | Count | Confusions covered |
|---|---|---|
| (a) Blocking did not offer the anchor case | 7 | IN_SAFETY_DB→NO_MATCH 4, SIGNIFICANT_FOLLOW_UP→NO_MATCH 3 |
| (b1) Agent ignored an offered candidate because its own `search_intake_queue` call returned nothing | 7 | IN_INTAKE_QUEUE→NO_MATCH 7 |
| (b2) Agent accepted a lookalike despite the country/date rule, or misread initial vs latest receipt date | 8 | NO_MATCH→IN_SAFETY_DB 6, NO_MATCH→SIGNIFICANT 1, IN_SAFETY_DB→NO_MATCH 1 |
| (b3) Agent matched the right (or an indistinguishable) case but mislabelled the follow-up type | 8 | IN_SAFETY_DB→NON_SIGNIFICANT 2, IN_SAFETY_DB→SIGNIFICANT 1, SIGNIFICANT→IN_SAFETY_DB 4, SIGNIFICANT→NON_SIGNIFICANT 1 |
| (c) Gold label debatable: FAERS holds near-duplicate cases with identical keys | 4 | NON_SIGNIFICANT→IN_SAFETY_DB 4 (2 of them also matched a neighbour id) |
| (d) Technical: rate limited four times, no decision | 3 | NO_MATCH→BLOCKED 3 |

### (a) Blocking: anchor not offered (7)

All seven anchors satisfy substance, sex, age band and date window. They fall out of the **`LIMIT 15`**: the
candidate query ranks by `lower(e.pt) IN (extracted terms)` and the extractor's term differs from the FAERS
PT (`Upper abdominal pain` vs `Abdominal pain upper`, `Exfoliative dermatitis` vs `Dermatitis exfoliative
generalised`, `Hyponatraemia` vs `Blood sodium decreased`, `Hepatocellular injury` vs `Hepatic cytolysis`,
`Multiple acyl-CoA…` vs `Multiple acyl-coenzyme A…`), so the anchor ranks with 40–267 same-key cases and
is cut. Examples:

- `PSP-007-0047` IN_SAFETY_DB: anchor `CONTOSO-23507989` (male 53, upper abdominal pain, received
  2025-12-09, record 2025-12-19); 40 same-key cases in window, anchor not in the top 15 → NO_MATCH.
- `PSP-007-0411` SIGNIFICANT_FOLLOW_UP: anchor received 2026-05-12, record 2026-05-23; 255 same-key
  cases; extractor said `Hepatocellular injury`, FAERS says `Hepatic cytolysis` → NO_MATCH.

### (b1) Intake-queue candidate offered, then dismissed (7)

In all seven the anchor intake item **was in the payload** (`INT-000xx`). The agent re-searched with
`search_intake_queue(text="Duloxane QT prolonged female 19 IE")`; the tool runs one `LIKE '%<whole
phrase>%'` on the summary (`Duloxane: Electrocardiogram QT prolonged, female 19y, IE`), returns 0 rows, and
the agent concluded NO_MATCH, in five cases citing rule 4 of the prompt ("vendor log has it, queue does
not: transmission gap"). The planted scenario also has the item in `PV.INTAKE_LOG`, which the agent has no
tool for. Example: `CRM-007-0157` (justification: "The intake queue search did not find the CRM item…").

### (b2) Lookalikes accepted, or receipt dates misread (8)

- Country mismatch accepted: `PSP-007-0051` (record PL, case FR: "the country mismatch is not enough to
  reject"), `PSP-007-0075` (DK vs RO), `CRM-007-0393` (BE vs FR, labelled SIGNIFICANT_FOLLOW_UP).
- Same country, keys identical, no identity beyond keys: `PQC-007-0375`, `PQC-007-0423`, `MI-007-0259`,
  `PSP-007-0053`. FAERS has such cases for common events (libido decreased, weight increased,
  hyponatraemia); a reviewer could not tell either, but the prompt lets the agent call a match on keys
  plus a plausible date.
- Initial vs latest date: `MI-007-0219` rejected the true anchor because `initial_receipt_date` is 2024
  although `latest_receipt_date` (2026-06-19) is one week before the record.

### (b3) Right case, wrong follow-up label (8)

The agent found the anchor (or an indistinguishable twin) but labelled the relation wrongly:

- SIGNIFICANT_FOLLOW_UP → IN_SAFETY_DB (4): the record adds a planted hospitalisation or a second event
  (`CRM-007-0389` adds a seizure; `MI-007-0149`, `PQC-007-0197`, `PSP-007-0199`) and the agent wrote "the
  candidate already captures the core case" or "the extra seizure/hospitalisation detail is not present
  in the history" and still chose IN_SAFETY_DB.
- IN_SAFETY_DB → NON_SIGNIFICANT_FOLLOW_UP (2) and → SIGNIFICANT (1): `MI-007-0417`, `MI-007-0431` repeat
  the case and the agent called the repeat a follow-up; `CRM-007-0027` read the FAERS case's own
  hospitalisation as new.

### (c) Gold debatable (4)

NON_SIGNIFICANT_FOLLOW_UP → IN_SAFETY_DB: the record says it repeats an earlier report; the agent
matched it and called it IN_SAFETY_DB. The two labels mean the same thing to PV (nothing new) and the
prompt's definitions overlap. In `CRM-007-0435` and `MI-007-0189` the agent also matched a neighbouring
case id with identical substance, sex, age, country and event (FAERS near-duplicates), which the gold
cannot distinguish from the anchor.

### (d) Technical (3)

`MI-007-0065`, `MI-007-0315`, `PSP-007-0147`: "rate limited four times". Agent calls and the text
renderer shared the 100 RPM deployment; the backoff ladder (10/30/60/90 s) was exhausted.

## 2. Rules

**Seriousness (23 disagreements, rule says not serious, gold says serious):**

| Gold event | n | Cause |
|---|---|---|
| Syncope | 9 | Catalogue marks syncope serious without hospitalisation ("other medically important"); not in the demo IME list; extractor never sets `other_medically_important` from text |
| Suicidal ideation | 3 | In the demo IME list, but the extractor proposed `Self-harm ideation` / `Self-injurious ideation`, so the exact-match IME lookup misses |
| Electrocardiogram QT prolonged | 1 | Same: extractor proposed `QT prolonged` |
| Abdominal pain, Burning sensation, Cold sweat, Alopecia, Drug abuse, Hepatitis cholestatic, Intentional overdose, mitochondrial myopathy, MADD | 10 | Anchored scenarios copy `serious` from the FAERS case (almost always true in FAERS) without planting a seriousness criterion in the text; nothing in the record supports it |

Only the hospitalisation flag and the IME list drive the rule; neither can recover these. 10 of 23 are
the gold's fault (anchored), 13 are vocabulary or list gaps.

**Ownership (3):** all three are PLANNED_PROCEDURE records (`PSP-007-0103`, `PSP-007-0209`,
`CRM-007-0273`). The extractor marked the product `suspect: false` because nobody links the admission to
the medicine; `product_ownership` ignores non-suspect products and returns `none`. The gold expects the
product the patient takes to be classified regardless of suspicion.

### Gold timing labels

The planner (`runner/pvsweep_synth/plan.py`) labels new cases `WITHIN_TIMELINE`, `FORWARDING_BREACHED` or
`OVERDUE`, but only moves the receipt date back for `OVERDUE`. The other two get a receipt date anywhere in
the 120 days before the reference date (2026-10-31), so many have passed their 15- or 90-day deadline by
the gold's own dates: 44 of 72 `WITHIN_TIMELINE` records and 27 of 48 `FORWARDING_BREACHED` records with a
gold day 0 are overdue at the reference date. The labels therefore cannot serve as the expected
regulatory status. The evaluation now derives the expected overdue flag from the gold day 0, the gold
seriousness and the run's `as_of` instead (`overdue_agreement` in `runner/pvsweep_runner/__main__.py`).
On `run-dc415c71681e` that gives 144 of 170. All 26 disagreements are records where the extraction found
the minimum criteria incomplete, so the clock never started. The next planner revision should constrain
the receipt date to the label: for `WITHIN_TIMELINE` and `FORWARDING_BREACHED`, day 0 plus the deadline
must fall on or after the reference date.

## 3. Proposals, in priority order

1. **Blocking (`runner/pvsweep_runner/blocking.py`), fixes (a):** before the ranked `LIMIT 15` query,
   add an exact-key pass with no term filter and no limit on date proximity: substance, same sex, age
   within ±1, `latest_receipt_date BETWEEN channel_received - 21 AND channel_received + 7`; union those
   case ids first, then the existing ranked query for the rest, de-duplicated, keeping at most 15 in
   total. Rank the term match with `rapidfuzz` partial ratio ≥ 80 (or a lowercase token overlap) instead
   of equality, so `Upper abdominal pain` ranks `Abdominal pain upper`. Expected: all 7 (a) cases
   offered; also helps (b2) by showing the exact-date twin first.
2. **Intake-queue tool (`runner/pvsweep_agent/matcher.py`, `search_intake_queue`), fixes (b1):** split
   the text on commas and spaces and require every token of length ≥ 4 to match (`AND lower(summary)
   LIKE '%tok%'` per token), and add `intake_id` as an optional argument so the agent can confirm a
   payload candidate directly. Add a `search_intake_log(vendor_code, vendor_reference)` tool, since the
   planted "received" scenarios live in `PV.INTAKE_LOG`.
3. **Prompt (`prompts/matching.md`), fixes (b1), (b2), (b3).** Replace step 1 and rule 4 with:

   > 1. The candidates in the payload were found by the pipeline's own search; treat them as real
   >    records. If a payload candidate fits on substance, patient and event, do not reject it because a
   >    tool search of yours returns nothing: confirm it with `get_case_history` or `search_intake_queue`
   >    using its id, then decide. Judge a safety-database candidate on substance, sex, age (a few years
   >    of difference or a missing age is fine), the event (synonyms count), the country and the dates.
   >    Use `latest_receipt_date`, not `initial_receipt_date`, for timing: the same report appears in the
   >    safety database between about three weeks before and one week after the record date. A different
   >    country is a mismatch unless the record itself gives no country. When several cases share the
   >    same keys, prefer the one whose latest receipt date is closest to the record date.
   > 4. An item in the vendor transmission log is evidence that the vendor forwarded it, not that
   >    pharmacovigilance holds it. If a payload candidate from the intake queue fits, the outcome is
   >    IN_INTAKE_QUEUE even when your own queue search finds nothing. Only when nothing in the safety
   >    database or the intake queue fits is the outcome NO_MATCH; then say whether the vendor log lists
   >    it (transmission gap).

   And add to the outcome definitions: "SIGNIFICANT_FOLLOW_UP applies whenever the record states a
   hospitalisation, death, a new event, or an outcome that the case history and the case's event list
   do not contain, even if the record also repeats the known event. NON_SIGNIFICANT_FOLLOW_UP applies only
   when the record presents itself as a later contact about an already reported case and adds nothing;
   a record that simply describes the same facts as the case is IN_SAFETY_DB."
4. **Planner (`runner/pvsweep_synth/plan.py`), fixes (c) and part of (b2):** for NEW_* kinds, reject a
   (substance, sex, age ±3, event, country) combination that already exists in `PV.SAFETY_CASE` with a
   latest receipt date inside the blocking window, and re-draw; for anchored kinds, skip anchors that
   have a same-key twin within 30 days (FAERS near-duplicates), so every anchor is unique.
5. **Seriousness, fixes most of the 23:** (i) planner: for anchored scenarios set `serious` from the
   case's `hospitalisation`/`death` flags only, or plant an explicit criterion in the facts ("led to a
   hospital stay"); (ii) extend the demo IME list with the catalogue's serious non-hospitalised events
   (`Syncope`, `Suicidal ideation` synonyms) and match IME terms with the same fuzzy comparison as
   blocking, or normalise the extractor's `proposed_term` against `REF.PT_VOCAB` before the lookup;
   (iii) prompt the extractor to set `other_medically_important` for events that are serious without
   admission (syncope, suicidal ideation, QT prolongation). Document that in production the licensed
   MedDRA + EMA IME list replace (ii).
6. **Ownership:** in `rules.product_ownership`, fall back to non-suspect products when no suspect product
   exists (the patient's own product still decides ownership); keep the `suspect` flag for the
   causality step.
7. **Rate limits (d):** make the agent runner's backoff ladder longer (up to 5 minutes total) and never
   run the renderer and a sweep against the same deployment at once; or raise `smallCapacity`.

Expected effect: (a)+(b1) alone are 14 of 37 disagreements; with (b3) and the lookalike rule the run
should move from 0.80 to about 0.93; the remaining (c) cases need the planner change.
