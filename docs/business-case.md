# Pharmacovigilance Sweep: Business Case

> For the head of PV operations and the IT/architecture sponsor of a mid-size EU marketing
> authorisation holder (MAH). Numbers from the repository name their source. Every other number is
> an assumption, listed in [Appendix A](#appendix-a-assumptions) so you can replace it. The POC uses
> public and synthetic data and is not a validated system.

## 1. The problem

Adverse events often reach systems owned by other functions before they reach PV. Those systems are
medical information logs, field-force CRM notes, patient support programme (PSP) notes, quality
complaints and social listening. The regulatory clock starts on day 0, when anyone in the MAH or
acting on its behalf holds the four minimum criteria: 15 calendar days for serious cases, 90 for
non-serious, restarted by significant follow-up (GVP Module VI, VI.B.7;
[poc-definition §2](poc-definition.md#2-business-problem)). The EMA has acted on PSP reports that
were never evaluated as potential adverse reactions (poc-definition §2).

| Waste | What it looks like |
|---|---|
| Unreviewed channels | Free text that nobody re-reads with PV eyes, including events nobody linked to the product (poc-definition §1) |
| Late detection | Every day before PV sees the record is lost from the 15-day window |
| Forwarding breaches | A vendor misses its SDEA timeline. This is a compliance finding, not a late case (poc-definition §6) |
| Reconciliation by hand | Vendor transmission logs checked against the PV intake log, vendor by vendor |

## 2. What the POC does and what it proved

The POC does two jobs:

- **Transmission reconciliation** is deterministic SQL.
- **Source re-screening** runs four steps: a small model screens each record, a model extracts the
  case facts, deterministic rules compute ownership, seriousness and the clocks, and a matching agent
  checks each record against the safety database, the intake queue and the vendor log.

Every surfaced record becomes a prioritised finding with a proposed case intake package. A PV
reviewer decides every outcome (poc-definition §3, §6).

| Capability | Scale | Result (source) |
|---|---|---|
| Infrastructure deployed by script to Sweden Central | Full | About 2 minutes (spike log, 2026-11-22) |
| GPT vs Claude | 450 records; local DuckDB backend, in-process agent; Claude through the Anthropic API | Table below ([comparison-round3](ops/comparison-round3.md)) |
| Claude on Foundry with Entra ID, Snowflake backend | 8 records | Screening 8/8, matching 8/8 (spike log, "night") |
| Hosted matching agents reading Snowflake | 8 records per provider | Matching: GPT 6/8, Claude 7/7 (spike log, "late") |
| Findings, intake packages, review app recording a decision | 4 records | Pass (spike log, 2026-11-23) |
| Foundry evaluation, three custom evaluators | Both round-3 exports | Matches the local evaluator (spike log, round 3) |
| Reconciliation views | Planted gaps | 20 PSP, 27 MI-vendor and 3 social-listening gaps found (spike log) |

The 450-record accuracies come from the local backend. The hosted path on Snowflake is so far
proven on samples only. The same runner code produced both sets of numbers.

| Round 3, 450 synthetic records | GPT (`gpt-5-4-mini` throughout) | Claude (Haiku 5.5; Sonnet 5.5 for matching and escalations) |
|---|---|---|
| Screening recall / precision | 0.997 / 1.0 | 0.968 / 1.0 (14 records got invalid JSON twice and were not routed) |
| Extraction valid share | 0.995 | 1.0 (after 61 escalations) |
| Causality statement / seriousness | 0.901 / 0.968 | 0.929 / 0.978 |
| **Matching accuracy** | **0.835** | **0.956** |
| Latency avg / p95, screen | 1.3 s / 2.7 s | 2.0 s / 3.2 s |
| Latency avg / p95, match (in-process) | 13.9 s / 27.1 s | 8.6 s / 11.8 s |

Source: comparison-round3. The provisional recall target is ≥ 95 % (poc-definition §9). The
synthetic set is enriched: 378 of 450 records should route (by-kind table). Measured precision
therefore probably overstates precision on real text.

**What a reviewer sees** (architecture §9): a queue ordered by seriousness, days left and
confidence. Each finding shows:

- the source text with the evidence highlighted;
- the extracted fields and the rule results;
- the match decision with its justification and tool-call log;
- the checklist and the proposed intake package.

A ranked 5 % sample of screened-out records goes to quality control (spike log, 2026-11-23).

## 3. Value model: a worked example

There are two counterfactuals: **(a) manual re-screening** of every record, and **(b) no
re-screening**. This document makes no claim about which one any MAH uses today.

**Base case (A1 to A6):**

- 8,000 records a month, of which 3 % carry an adverse event or special situation: 240 records.
- 95 % of those are already held by PV: 228 known, 12 new or significant follow-up.
- Manual triage takes 2 min per record, and assessing a finding takes 15 min.
- Reviewer time costs EUR 60/h.

**Model rates:**

- Screening recall and precision as measured.
- Accuracy on records PV already holds is derived here from the comparison-round3 by-kind table. It
  weights the IN_SAFETY_DB, IN_INTAKE_QUEUE and NON_SIGNIFICANT_FOLLOW_UP rows by n (98 records):
  **GPT 0.60, Claude 0.86**.
- Every matching error on a known record is assumed to add a finding. This is conservative.

**(a) Manual:** 8,000 × 2 min + 240 × 15 min = 19,600 min = **327 h/month**, about 2.0 FTE (A7), or
**EUR 19,600**.

**With the sweep:**

| Step | GPT | Claude |
|---|---|---|
| New or significant follow-up routed (12 × recall) | 12.0 | 11.6 |
| Known records misread (228 × recall × (1 − 0.60 or 0.86)) | 90.4 | 31.8 |
| False positives (7,760 × (1 − precision)) | 0 | 0 |
| **Findings to review** | **102** | **43** |
| Findings at 15 min | 25.6 h | 10.9 h |
| QC: 5 % of about 7,760 screened-out records at 2 min | 12.9 h | 12.9 h |
| **Reviewer hours / month** | **38.5 h** | **23.8 h** |
| Cost at EUR 60/h | EUR 2,312 | EUR 1,429 |

Claude also leaves 7.7 positives a month unrouted (invalid JSON). Routing them to review would add
about 2 h.

**Sensitivity:**

- **Precision:** at 2 % false positives on real text (A8), the hours rise to 77 h for GPT and 62 h
  for Claude, still under a quarter of the manual figure.
- **Reconciliation:** automating it saves about 12 of 16 h a month (A9).

**(b) No re-screening.** This costs no hours. In the base case it leaves about **12 potential new
cases or significant follow-ups a month** unseen. The risk is expressed as lost clock days, not as
a fine.

**Cadence matters.** A weekly sweep (A10) finds an unforwarded serious case at most about 7 days
after day 0, leaving at least 8 of its 15 days. That is the situation in the poc-definition §6
example: the forwarding timeline is breached but the case is not late. A monthly sweep would find
most such cases after their deadline. Each record is screened once, so cadence does not change model
cost.

## 4. Costs

**Model cost per sweep of 450 records** (architecture §11, list prices):

- **Screening and extraction (audited call by call):**
  - GPT: $0.47 + $0.96.
  - Claude: $0.08 + $1.23.
- **Matching (estimated from prompt sizes, because the agent's tokens are not yet audited):**
  - GPT: about $9.
  - Claude: about $10 at the observed cache hit rate, or $23 without caching.
- **Total:** about $11 per provider.

In the worked example, screening covers all 8,000 records, while extraction and matching cover only
the roughly 235 routed records. That gives **about $15 a month for GPT and $9 to $17 for Claude**.

**Platform:**

- Hosted-agent compute (0.5 vCPU, 1 GiB) "was negligible in the spike" (architecture §11).
- Snowflake runs on an XS warehouse.
- The Azure pieces are a Container Apps job, Key Vault, a Basic registry and Application Insights
  (architecture §3).

The repository does not price any of these. A11 to A13 assume about EUR 350 a month, to be priced
by IT.

**Monthly run-rate** (EUR; model cost in USD taken at par, which is immaterial at this size)

| Volume | Manual (a) | Sweep, GPT | Sweep, Claude |
|---|---|---|---|
| 1x: 8,000 records | 19,600 | 2,312 + 15 + 350 = **2,677** | 1,429 + 9–17 + 350 = **1,788–1,796** |
| 2x: 16,000 records | 39,200 | 4,624 + 29 + 550 = **5,203** | 2,857 + 17–34 + 550 = **3,424–3,441** |
| 5x: 40,000 records | 98,000 | 11,560 + 74 + 1,150 = **12,784** | 7,143 + 43–85 + 1,150 = **8,336–8,378** |

People time is 80 to 90 % of the sweep run-rate, so the model is not the cost driver. The figures
exclude the production additions in section 7, which are to be estimated in phase 2.

## 5. Provider choice

**What the evidence says** (comparison-round3 and spike log, round 3):

- **Matching:** Claude leads overall. The gap is in the hard kinds:

  | Kind | GPT | Claude |
  |---|---|---|
  | Already in the safety database | 0.447 | 0.795 |
  | Significant follow-up | 0.393 | 1.0 |
  | Non-significant follow-up | 0.333 | 0.75 |

  Claude confirms candidates against the case history. GPT more often rejects a candidate after its
  own search finds nothing.
- **Causality:** Claude is slightly ahead.
- **Routing:** GPT is ahead, because Claude returned invalid JSON twice on 14 records.
- **Cost per sweep:** about equal.

**Fairness caveat.** GPT used `gpt-5-4-mini` throughout, because `gpt-5.5` had 0 TPM as EU Data Zone
Standard (spike log, "Facts learned"). Claude matched with Sonnet 5.5. The matching gap therefore
partly compares a mini model with a large one.

**Data residency** (architecture §3, §12):

- GPT runs as EU Data Zone Standard.
- Claude on Foundry offers Global Standard or a US data zone only. Some operational data is stored
  outside Azure, and Anthropic acts as an independent processor for Microsoft.
- Personal health data would need pseudonymisation before model calls, or a GDPR transfer
  assessment. Which one is acceptable is to be confirmed with the DPO and the QPPV.
- The POC's Snowflake account is on AWS eu-west-3 (spike log, "night").

| Option | For | Against |
|---|---|---|
| A. GPT throughout, EU Data Zone | Simplest residency | On current evidence 38.5 h vs 23.8 h of review a month and weaker follow-up labels; may improve with `gpt-5.5` |
| B. Claude throughout | Best measured matching and causality | Transfer assessment or pseudonymisation; invalid-JSON routing fix |
| C. GPT screens and extracts in the EU; Claude matches pseudonymised candidates | Highest recall plus the best matching | Two providers to operate and validate; pseudonymisation design unproven |

**For the sponsor's decision:** keep both providers through phase 1, then decide after a
tier-matched GPT run and the full Claude-on-Foundry run. If residency must be EU-only, the answer is
A. Otherwise C is the option to pilot. The agent code is identical on both providers (spike log,
"late"), so a later switch is a configuration change, not a rewrite.

## 6. Risks and mitigations

| Risk | In the POC | Production would add |
|---|---|---|
| **Silent drop:** a new record judged "already held" never reaches a reviewer | Only new, significant follow-up and blocked records become findings (spike log, 2026-11-23). On kinds PV does not already hold (new records, special situations, incomplete reports, other MAHs' products) GPT scores 0.917–1.0 and Claude 1.0, except planned procedures at 0.882 and special situations at 0.966. These are upper bounds, because the table does not show which way the errors went | A QC sample of auto-linked records |
| Screening failures | Detected and logged, but not routed | Route every failure to review; Sonnet retry (spike log, round 3) |
| Wrong extracted facts or dates | Schemas, evidence spans, validation after every call, deterministic clocks (ADR-005). Overdue flag correct on 144/170; all 26 misses had incomplete criteria (spike log, 2026-11-23) | Reviewer confirms day 0, as in the POC; three-run consistency |
| Prompt injection in source text | Select-only `AGENT_API` views and a strict submit tool (architecture §3, ADR-010). Prompt Shields cover GPT; Claude coverage is to be confirmed. Guardrails on overdose text are untested | A red-team set in the evaluation |
| Data residency | Synthetic data only | Option A or C, a DPA, and retention for agent sessions and traces (architecture §12) |
| Quota | Claude started at 0 TPM (granted within the day); `gpt-5.5` at 0 TPM (spike log) | Quota agreed before go-live; API Management (architecture §16) |
| Vendor lock-in | Same agent code on both providers; DuckDB mirror; Cortex documented as an alternative (ADR-002, ADR-013) | The evaluation suite used as exit tests |
| Validation and GxP | Not validated; append-only audit of every call and decision (ADR-007) | Risk-based validation (GAMP 5, CSA; architecture §16) and change control on prompts and models; scope to be confirmed with QA and the QPPV |
| Synthetic optimism | Scenario-first data with a validator (poc-definition §8) | A pilot on real records |

## 7. Roadmap to production

| Phase | Scope | Unblocks |
|---|---|---|
| **1. Complete the evidence** (indicative 4–6 weeks, A14) | 450 records through Claude on Foundry and the hosted agents on Snowflake; tier-matched GPT run; failure routing; guardrail and session-reuse tests; Container Apps runner job; three-run consistency | The provider decision, on like-for-like evidence |
| **2. Pilot on one channel** (indicative 3 months) | One PSP or MI vendor with real records; pseudonymisation or transfer assessment; network isolation; licensed MedDRA; real reviewers measuring minutes per finding and real-text precision | Measured values for A1 to A9, and a priced production design |
| **3. Production** | All five channels, validation and change control, API Management, multilingual intake, SOP and SDEA updates | An inspection-ready control with recorded results (poc-definition §7) |

**Decision asked of the sponsor:**

1. Approve phase 1 and a phase-2 pilot on a named channel.
2. Set the residency position (EU-only, or a transfer assessment allowed).
3. Name the QPPV delegate and the QA contact for the validation scope.

## Appendix A. Assumptions

| # | Assumption | Base | Range |
|---|---|---|---|
| A1 | Records per month, five channels | 8,000 | 4,000–20,000 |
| A2 | Share with an adverse event or special situation | 3 % | 1–5 % |
| A3 | Share of those already held by PV | 95 % | 90–99 % |
| A4 | Manual triage per record (also QC review) | 2 min | 1–4 min |
| A5 | Assessment per finding | 15 min | 10–30 min |
| A6 | Loaded reviewer cost | EUR 60/h | EUR 45–90/h |
| A7 | Productive hours per FTE-month | 160 | 140–170 |
| A8 | False-positive rate on real text (measured 0 on synthetic) | 0 % | 0–5 % |
| A9 | Manual reconciliation: vendors × hours a month (1 h per vendor left after automation) | 4 × 4 h | 3–8 × 2–8 h |
| A10 | Sweep cadence | Weekly | Daily–weekly |
| A11 | Hosted-agent compute, to be priced | EUR 50 | EUR 20–150 |
| A12 | Snowflake XS warehouse, to be priced (1x / 2x / 5x) | EUR 200 / 400 / 1,000 | EUR 100–400 at 1x |
| A13 | Azure platform pieces, to be priced | EUR 100 | EUR 50–200 |
| A14 | Phase durations | Section 7 | To be planned |
| A15 | Every matching error on a known record adds a finding | Yes | Upper bound |

## Appendix B. Evidence summary

| Claim | Evidence |
|---|---|
| Problem, channels, clocks, checklist, outcomes | [poc-definition.md](poc-definition.md), sections 2, 5, 6, 7 |
| Architecture, residency, security, ADRs, cost per sweep | [architecture.md](architecture.md), sections 3, 11, 12, 15 |
| Every measured result, from deployment to the review app | [ops/spike-log.md](ops/spike-log.md) |
| GPT vs Claude by generator, scenario kind, cost and latency | [ops/comparison-round3.md](ops/comparison-round3.md) |
| Matching error analysis, gold timing labels | [ops/matching-analysis.md](ops/matching-analysis.md) |
| Claude quota on Foundry | [ops/claude-quota-request.md](ops/claude-quota-request.md) |
| Repository status and deployment | [README.md](../README.md) |

Status, 2026-11-23:

- Infrastructure, data, Snowflake, the review app and both hosted agents work end to end.
- Model quality is measured on 450 synthetic records.
- Business KPIs are simulated and need a pilot (poc-definition §9).
