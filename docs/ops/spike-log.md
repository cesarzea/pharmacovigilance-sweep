# Spike log

Results of the go/no-go spike in [architecture.md](../architecture.md), section 17. Everything below was
created by the repository's scripts (`make deploy`, `make build-agent`, `make deploy-agents`).

## 2026-11-22

| # | Check | Result |
|---|---|---|
| 0 | Foundry resource, project, `gpt-5-4-mini` (EU Data Zone Standard), budget, registry, runner identity and roles deployed from `infra/` to Sweden Central | **Pass.** `make deploy`, about 2 minutes |
| 0 | `claude-haiku-5-5` deployment | **Blocked.** Preflight `InsufficientQuota`: every Claude model has 0 TPM in the subscription. Support ticket <ticket id> open; see [claude-quota-request.md](claude-quota-request.md) |
| 0 | GPT call with Entra ID and a strict JSON schema from a laptop (`spike/01_entra_model_calls.py`) | **Pass.** 1.5 s, valid JSON, 153 input / 30 output tokens |
| 0 | Agent Framework agent with tools, in-process against `gpt-5-4-mini` | **Pass.** 5.7 s, two tool calls, terminal tool returned |
| 1 | Hosted agent reaches the internet from its sandbox | **Pass.** `probe_url` from inside the hosted agent: `example.com` 200, `snowflakecomputing.com/robots.txt` 403 (a web application firewall answer, so the connection itself worked). Snowflake proper is tested once the trial account exists |
| 2 | Hosted agent calls Claude with Entra ID through Agent Framework | **Pending** on Claude quota. The code path is written (`agent/app.py`, `MODEL_PROVIDER=claude`) |
| 3 | Same agent code on both providers, always ends with the submit tool | **Half.** GPT: the hosted agent returned the `submit_result` JSON on both invocations. Claude pending |
| 4 | Reused sessions start with fresh state | **Pass** (2026-11-23). The platform routes by the `agent_session_id` query parameter only; echoing the `x-agent-session-id` header back is ignored (four calls, four sessions). With the parameter, three further calls landed in the same session: 6.5 s for the first call, then 1.4 s, 1.1 s and 1.1 s. The runner now keeps a per-agent pool of free session ids (at most `concurrency` sessions); the hosted agent holds no state between invocations, so reuse cannot carry one record into the next |
| 5 | Guardrail behaviour on overdose and self-harm text | **Pass** (2026-11-23). Three texts through the screening prompt on both providers with the default content filter (`Microsoft.DefaultV2`): a PSP note describing an intentional overdose with suicidal ideation, a forum post describing self-harm, and a control without PV content. GPT and Claude Haiku both answered `ADVERSE_EVENT`, `ADVERSE_EVENT`, `NO_PV_CONTENT` with status ok: nothing was blocked or annotated, so suicide- and self-harm-related reports reach assessment |
| — | Invocations protocol end to end (`spike/02_invoke_hosted_agent.py`) | **Pass.** HTTP 200; 13.5 s for the two-probe call, 9.0 s for a trivial call. Each call without a session id got a new session (`x-agent-session-id` differs), so session reuse must be explicit |

## 2026-11-22, later: data, synthetic records, end-to-end sweep (local backend)

| Check | Result |
|---|---|
| Public data staged (`make stage-data`) | **Pass.** FAERS: 10,077 EU/EEA cases with the four substances as suspect, dates shifted by 669 days, brands remapped; VAERS: 400 coding and 400 outcome rows; vocabulary 18,470 terms. Hugging Face rate-limits DuckDB's remote reads, so files are downloaded once into `data/cache/` |
| Scenario plan (`pvsweep_synth plan`) | **Pass.** 450 scenarios over 13 kinds and 5 channels; 93 anchored on real FAERS cases; intake queue 33, intake log 85, vendor log 135 rows. Deterministic for the seed; every rendered text carries a hash of its scenario |
| Text rendering with GPT (`pvsweep_synth render --share 1/2`) | **Pass.** 225 records, 223 validated at the first attempt; about 1,200 tokens per record including retries. Claude's half waits on a working Anthropic key (the key authenticates but every call returns 429 with no rate-limit headers: account-side limit to check in the Console) |
| Sweep, 40 records, GPT, agent matching in-process | **Pass.** Screening recall 1.000 (33/33 routed, 0 false positives on 7 non-PV records). Extraction valid 33/33, 2 escalations; causality statement 30/33, sex 31/33, age 31/33. Rules: ownership 33/33; seriousness 26/33 (the misses are "other medically important" events that need the IME list, e.g. syncope). Matching 30/33 (0.909): one BLOCKED, two confusions between "already in the safety database" and "non-significant follow-up". 250 s wall-clock at concurrency 3; 75 audited model calls, about $0.13 for screening and extraction (the agent's calls are not yet audited in-process) |
| Report views (`V007`) on the local backend | **Pass.** Reconciliation finds 20 PSP, 27 MI-vendor and 3 social-listening items sent but never received, as planted |
| Sweep, 225 GPT-rendered records, GPT, agent matching | **Pass with findings.** Screening recall 1.000 (191/191, 0 false positives; 2 ADVERSE_EVENT read as SPECIAL_SITUATION). Extraction valid 188/191; causality 173/191, sex 185, age 185. Matching 151/188 (0.803); the 37 disagreements are analysed in [matching-analysis.md](matching-analysis.md): blocking cut the true case out of the top 15 (7), the agent dismissed an offered intake item after its own phrase search found nothing (7), lookalikes accepted against the country/date rule (8), right case but wrong follow-up label (8), debatable gold on FAERS twins (4), rate-limit blocks (3). 22 minutes at concurrency 3; 419 audited calls; about $0.71 for screening and extraction plus the agent's calls |
| Foundry custom evaluators | **Pass.** Three code-based evaluators registered in the project (`scripts/foundry_evaluate.py`) and an evaluation run completed on the exported 225-record run: routing 225/225, matching outcome 151/225, causality statement 170/225, with the report in the Foundry portal. The same grade functions as `pvsweep_runner.evaluate` |
| Claude Sonnet 5.5 renders the other half (Anthropic API) | **Pass.** 225 records, 224 validated; texts are about twice as long as GPT's (115 vs 57 words) and more structured |

Two things changed the matching accuracy from 0.71 to 0.91 between the first and second runs:
a stricter instruction (a lookalike with the same substance, sex and event is not a match unless
country and dates agree) and country plus receipt dates in the candidate keys. The first run also
showed that anchored scenarios need dates consistent with their case, which the planner now does.

## 2026-11-22, round 2: fixes from the analysis, both generators, 450 records

| Check | Result |
|---|---|
| Fixes applied (blocking exact-key pass and fuzzy terms, token-wise intake search, `search_intake_log`, prompt v2, IME synonyms, ownership fallback, unique anchors, seriousness from the case) | Done; 14 unit tests pass; 93 anchored scenarios re-rendered by both generators |
| Sweep, 450 records (225 GPT-written, 225 Claude-written), GPT, agent matching | Screening recall 0.997 (377/378), 0 false positives. Extraction valid 372/377, escalated 16; causality 338/377, sex 364, age 366. **Rules now agree on seriousness 367/372** (was 165/188) and ownership 362/372. **Matching fell to 0.694** (258/372): the exact-key pass now offers FAERS lookalikes to every new record and the agent accepts them (37 NO_MATCH read as IN_SAFETY_DB), and the token-wise intake search over-matches (15 NO_MATCH and 16 known cases read as IN_INTAKE_QUEUE); anchored cases still missed 18 times |
| Sweep, same 450 records, Claude (Haiku 5.5 screening and extraction, Sonnet 5.5 agent, Anthropic API) | Screening recall 0.989 (4 records answered with invalid JSON twice), 0 false positives. Extraction valid 374/374 after 50 escalations to Sonnet; causality 350/374. Seriousness 364/374, ownership 363/374. **Matching 0.844** (314/372): only 2 lookalikes accepted, but 18 known cases and 16 significant follow-ups missed as NO_MATCH. Full side-by-side in [comparison-round2.md](comparison-round2.md): on the 406 records both runs share, GPT 0.729 vs Claude 0.903 matching, screening and extraction within a point of each other |
| Conclusion | Without a patient identifier the safety database cannot be searched reliably: with 10,000 cases on four substances, same substance, sex, age and event within weeks is common. Real safety databases hold patient initials, and FAERS does not, so round 3 adds deterministic synthetic initials to the extract, carries them into the intake queue summaries and the agent's tools, and makes initials the primary identity rule in the prompt. Queue candidates are offered only when the event or the initials agree |

## 2026-11-22, round 3: patient initials and prompt v3, both providers, 450 records

| Check | Result |
|---|---|
| Changes (synthetic initials on every safety case and intake summary, `search_safety_cases(initials)`, queue candidates only when event or initials agree, prompt v3 with initials as the identity rule) | Done; 14 unit tests pass; the 450 records re-planned so anchored scenarios carry their case's initials |
| Sweep, 450 records, GPT (`gpt-5-4-mini` everywhere) | Screening recall 0.997, 0 false positives. Extraction valid 375/377; causality 0.901, seriousness 0.968. **Matching 0.835** (313/375, was 0.694). Lookalikes are gone (3 NO_MATCH read as IN_SAFETY_DB, was 37); what remains is known cases missed as NO_MATCH (16) or sent to the intake queue (10), and follow-ups missed the same way (17 of 46). 2 blocked |
| Sweep, same 450 records, Claude (Haiku 5.5 screening and extraction, Sonnet 5.5 agent, Anthropic API) | Screening recall 0.968: Haiku answered 14 records with invalid JSON twice and they were not routed, 0 false positives. Extraction valid 366/366 after 61 escalations to Sonnet; causality 0.929, seriousness 0.978. **Matching 0.956** (346/362, was 0.844): 1 lookalike accepted; the 16 errors are mostly follow-up labels (6 known cases read as significant follow-up, 3 non-significant read as significant) and 2 blocked |
| Side by side ([comparison-round3.md](comparison-round3.md)) | By scenario kind, Claude is at or near 1.0 on every new-record kind and on follow-ups (28/28 significant); GPT's gaps are IN_SAFETY_DB 0.447, NON_SIGNIFICANT_FOLLOW_UP 0.333, SIGNIFICANT_FOLLOW_UP 0.393. Screening and extraction stay within two points of each other, with GPT ahead on routing (the invalid-JSON retries) and Claude ahead on causality and seriousness. Audited calls: GPT 1,210, Claude 1,239; prompt caching served 1.9 M of Claude's input tokens |
| Foundry evaluation on the exports | Both round-3 exports graded by the three registered evaluators in the project. GPT: routing 449/450, matching 313/450, causality 338/450. Claude: routing 437/449, matching 346/450, causality 340/450. The same numbers as `pvsweep_runner.evaluate` on the laptop, with the reports in the Foundry portal |
| Conclusion | With an identifier the problem is tractable: both providers stop accepting lookalikes. What separates them now is how they treat a candidate that fits on initials: Claude confirms it with `get_case_history` and reads the version history for the follow-up label; GPT more often rejects it after its own search returns nothing, or stops at the intake queue. Next steps are a screening retry on Sonnet for invalid JSON, a follow-up rubric in the prompt, and the same runs through Claude on Foundry once the deployment finishes |

## 2026-11-22, night: Snowflake for real, Claude on Foundry for real

| Check | Result |
|---|---|
| Snowflake account | The user's own account (AWS eu-west-3, Paris). CLI connections `pvsweep-admin` and `pvsweep`; `make snow-bootstrap`, `make snow-migrate` (V001 to V008), `make snow-load`, `make snow-app` all run from the repo. Three SQL fixes on the way: one grantee and one schema per `GRANT`, no `IDENTIFIER(CURRENT_USER())` in a grant, no `GRANT OWNERSHIP` on a Streamlit; details in [snowflake-setup.md](snowflake-setup.md) |
| Data load | 14 Parquet files, 10,077 safety cases and all synthetic tables loaded with `MATCH_BY_COLUMN_NAME`. First load had every `TIMESTAMP` column in year 56 million: Snowflake reads DuckDB's microsecond timestamps as nanoseconds unless the file format says `USE_LOGICAL_TYPE = TRUE`. Also: `make snow-load` must re-stage first, or the records in Snowflake lag behind the committed synthetic set (the first sweep matched against texts without initials) |
| Service users | `PVSWEEP_RUNNER` (pipeline role) and `PVSWEEP_AGENT` (AGENT_API views only) authenticate with their RSA keys from the runner; the agent user cannot read the `PV` schema, as designed |
| Sweep, 8 records, GPT, Snowflake backend, in-process agent over the `AGENT_API` views | **Pass.** Screening 8/8, extraction 8/8, rules 8/8, matching 5/8 (three known cases read as NO_MATCH, the same gap as on the laptop); 24 audited calls in `AUDIT.MODEL_CALL`; 69 s |
| Sweep, 8 records, **Claude on Foundry** (Haiku 5.5 screening and extraction, Sonnet 5.5 agent, Entra ID only), Snowflake backend | **Pass.** Screening 8/8, extraction 8/8 (1 escalation), rules 8/8, **matching 8/8**; 25 audited calls; 271 s. The same runner code that produced the Anthropic-API numbers above, now on the evaluated path |
| Claude deployments from Bicep | **Pass after a fix.** `claude-haiku-5-5` and `claude-sonnet-5-5` (Global Standard, 50 K TPM each) are `Succeeded`. Two earlier attempts failed with `AnthropicOrganizationCreationFailed` because `modelProviderData.industry` was `Professional Services`; the field is a lowercase enum (`healthcare` here) and `infra/main.bicep` now constrains it |
| Streamlit review app in Snowflake | **Pass.** `REVIEW.PVSWEEP_REVIEW` renders the sweep runs over the real tables (owner's rights, PVSWEEP_ADMIN); column names from Snowpark arrive upper-case, so the app lower-cases them |
| Runner changes | Snowflake connector added to the runner project; `.env` is loaded at CLI start; the in-process agent backend serialises its shared connection and takes its own key variable; the end-of-run summary SQL is dialect-aware; `--account`/`--small` are required for Foundry providers; run-time role gets `UPDATE` on `SWEEP.RUN` only (V008) |

## 2026-11-22, late: hosted agents on both providers, reading Snowflake from the sandbox

| Check | Result |
|---|---|
| Agent key in a Foundry project connection (`infra/modules/connections.bicep`, `${{connections...}}` placeholder) | **Pass.** The sandbox received the PEM key through the environment; nothing secret in the image or the agent definition |
| Hosted agent entry point (`agent/app.py` implements `SupportsAgentRun`) | **Pass after two rewrites.** A wrapper Agent with a `match` tool failed on `asyncio.run` inside the host loop, then on Claude because the model had to echo the whole payload into a tool-call argument (truncated, HTTP 500). The entry point now hands the Invocations message straight to the matcher |
| Claude hosted agent calling Claude on Foundry with its own identity | **Pass** once the agent identity holds *Azure AI User* on the account (granted by `scripts/deploy_agents.py`); HTTP 500 "Agent invocation failed" before that |
| Sweep, 8 records, GPT, `--match hosted`, Snowflake backend | **Pass.** Screening 8/8, extraction 8/8, matching 6/8 (two known cases read as NO_MATCH); 91 s at concurrency 2 |
| Sweep, 8 records, Claude on Foundry, `--match hosted`, Snowflake backend | **Pass.** Screening 8/8, matching 7/7; one record lost to a transient TLS error on the laptop's Haiku call (`ConnectError`, counted as invalid, re-runnable with `--resume`); 152 s |
| Spike items 1 to 3 of section 17 | Closed: Snowflake egress from the sandbox, Claude with Entra ID through Agent Framework, same code on both providers ending with the submit tool. Items 4 (session reuse) and 5 (guardrails) stay open |

## 2026-11-23: findings, case intake package, review flow on Snowflake

| Check | Result |
|---|---|
| Findings step (`runner/pvsweep_runner/findings.py`) | **Pass.** Every routed record that is new, a significant follow-up or blocked becomes a `potential_case` finding with a priority score and a proposed case intake package (JSON, `case-intake-package:v1`); a ranked 5 % sample of screened-out records becomes `qc_sample` findings. 36 unit tests pass |
| Post-match clock | Records already held by PV (in the safety database, in the intake queue, non-significant follow-up) get `no_new_clock` after matching; `REPORT.CHANNEL_KPI.overdue_at_detection` on the 450-record GPT run falls from 181 to 136 once those stop counting |
| Overdue evaluation | The gold timing labels contradict the planted dates for 71 of 120 labelled records ([matching-analysis.md](matching-analysis.md), "Gold timing labels"), so the check now derives the expected flag from the gold day 0 and seriousness: 144 of 170 agree on the 450-record run, and all 26 misses are records whose extraction found the minimum criteria incomplete |
| Sweep on Snowflake with findings (4 records, GPT) | **Pass.** 3 potential cases written to `SWEEP.FINDING` with packages; V009 applied |
| Review app on Snowflake | **Pass.** Queue from `SWEEP.FINDING` by priority; opening a finding shows the package; recording outcome D with a confirmed day 0 wrote `REVIEW.DECISION`, `REVIEW.CASE_INTAKE_PACKAGE` (deadline recomputed from the confirmed day 0) and `REVIEW.COMPLIANCE_FINDING` (`late_submission`) in one click, with the viewer's name from `st.user` |

## 2026-11-23: the sweep as an unattended Azure job

| Check | Result |
|---|---|
| `infra/modules/runner.bicep` deployed (`make deploy DEPLOY_RUNNER=1`) | **Pass.** Log Analytics (30-day retention), App Insights, Key Vault (RBAC: runner identity Secrets User, deploying principal Secrets Officer), AcrPull for the runner identity, consumption-only Container Apps environment, manual-trigger job `job-pvsweep-dev-sweep` (0.5 vCPU / 1 GiB, no retries). Order on a fresh environment: build the image, deploy without jobs, `make kv-secrets`, deploy with jobs; see [runner-job.md](runner-job.md) |
| Secrets | The two Snowflake private keys go to Key Vault by file (`scripts/kv_secrets.sh`) and reach the job as Key Vault secret references resolved with the runner's identity; nothing passes through shell arguments or the repository |
| Execution `job-pvsweep-dev-sweep-fbcccyc` (`make run-sweep-job`, `--limit 6`, GPT) | **Pass.** 3 min 07 s wall-clock (146 s for the sweep itself); `SWEEP.RUN` row `run-054e4b5e2af1` with 6 screened, routed, extracted and matched, 5 potential-case findings, 18 audited calls, about $0.02. Console logs reach Log Analytics about five minutes after the end; `az containerapp job logs show` answers "No replicas found" once the execution is over |
| Guard rails | `scripts/run_sweep_job.sh` refuses to start without `--limit` unless `ALLOW_FULL_SWEEP=1`, starts the job through the ARM API with an args override, and stops the execution if the override did not reach it. The 50 EUR budget on the resource group covers the new resources. `SWEEP.RUN.code_version` records the image tag |

## 2026-11-23: round 3 on the evaluated path, Claude on Foundry over Snowflake, 450 records

| Check | Result |
|---|---|
| Sweep, 450 records, Claude on Foundry (Haiku 5.5 screening and extraction, Sonnet 5.5 agent, Entra ID), Snowflake backend, in-process agent, concurrency 2 (`run-fe888fb4684e`) | **Pass.** Screening recall 0.976 (9 records lost to Haiku's invalid JSON twice, 1 false positive), extraction valid 370/370 after 51 escalations, causality 0.938, seriousness 0.973, **matching 0.954** (349/366, 3 blocked). 2 h 51 min wall-clock; 1,237 audited calls, $1.15 for screening and extraction at list prices (the agent's Sonnet tokens are not reported by the framework) |
| Same code, Anthropic API vs Claude on Foundry (`comparison-round3-foundry.md` and the Anthropic run of round 3) | Within half a point on every metric: matching 0.956 vs 0.954, screening recall 0.968 vs 0.976, causality 0.929 vs 0.938. The two hosting paths are interchangeable for quality; the Foundry path adds Entra ID, EU billing and the audit in Snowflake. Foundry evaluation of the export: routing 440/450, matching 349/450, causality 347/450 |
| Throughput at 50 K TPM per deployment | About 2.6 records per minute: screening 2 s, extraction 11 s (Sonnet 21 s), matching 32 s average per record with 429 back-offs up to 10 minutes on single calls. Levers for production, none in code: deployment capacity to the 80 K TPM granted (`largeCapacity` in Bicep), concurrency 4, Haiku in the agent if a sample shows the accuracy holds |
| Snapshot of a Snowflake run to a local file (`pvsweep_runner.snapshot`) | **Pass.** Copies a run's result and audit rows by column name into a LocalStore file, so `evaluate` and `compare` work on Snowflake runs; the same mapping serves a platform migration |

## Facts learned

- **Hosted agents and secrets:** a `CustomKeys` project connection created from Bicep
  (`infra/modules/connections.bicep`) and referenced as `${{connections.<name>.credentials.<key>}}` in
  the agent's environment variables is resolved by the platform at start-up: the sandbox saw the full
  PEM key (1,703 characters). No secret is in the agent definition, the image or the repository.
- **Hosted agents and Claude:** the platform mints an identity per hosted agent (`instance_identity`
  in the version record). GPT through the project endpoint works without any role, but Claude on
  Foundry is called with that identity's token against the account's `/anthropic` endpoint and fails
  with HTTP 500 "Agent invocation failed" until the identity holds *Azure AI User* on the account;
  `scripts/deploy_agents.py` grants it after each version becomes active.
- **Hosted agent tools run inside the host's event loop:** a sync tool that calls `asyncio.run()`
  fails with "Function failed"; the tool is `async` and awaits the matcher. Tool failures now come
  back as a JSON error with safe diagnostics instead of an opaque message.
- **Image layout:** `prompts/` is one level above the package in the image and two in the repository;
  the matcher looks in both (or `PVSWEEP_PROMPTS_DIR`).
- **Anthropic API keys and workspaces:** an organisation-level key must send `anthropic-workspace-id`;
  without it the API answers 400, and a key with no credit attached answers 429 `rate_limit_error`
  with no rate-limit headers. Only a workspace created in the Console for API use works (another
  workspace in the organisation answered 404 on messages). The runner reads `ANTHROPIC_WORKSPACE_ID`
  from `.env`.

- **`modelProviderData.industry` is a lowercase enum** (technology, finance, healthcare, education, retail,
  manufacturing, government, media, other). Any other spelling fails the deployment after minutes of
  polling with `AnthropicOrganizationCreationFailed: Internal Server Error`, which looks like a backend
  outage and is not. Quota was granted on the support ticket within the day.
- **Claude quota is 0 by default on this pay-as-you-go subscription**, for every Claude model and both
  hosting versions. Microsoft's own portal diagnostics confirmed "no initial Claude quota allocated".
  The API support route needs a paid plan; the portal accepts quota tickets on the Basic plan under
  *Service and subscription limits (quotas)* → *Cognitive Services*.
- **`gpt-5.5` has 0 TPM as EU Data Zone Standard** too; only `gpt-5.4-mini` (200K TPM) and `gpt-5-mini`
  (500K, Global) have quota. Requested in the same ticket.
- **Environment variables named `FOUNDRY_*` or `AGENT_*` are reserved** in hosted agent definitions; the
  platform injects `FOUNDRY_PROJECT_ENDPOINT` itself. Ours are `PVSWEEP_*`.
- **Registry pull role:** *Container Registry Repository Reader* on the project identity did not let the
  platform pull the image (`ImageError: Container registry authentication failed`); `AcrPull` did. The
  repository-scoped role needs the registry's ABAC permissions mode. Role propagation took under two
  minutes.
- **`az acr build` rejects `FROM --platform=...`** in the Dockerfile; the platform goes on the command line.
- **Sandbox size** `0.5` vCPU / `1Gi` is enough for the agent image (Python 3.13 slim plus Agent Framework).
- The project's Foundry resource name resolves a minute or two after creation; `az acr build` needs
  `-g` right after deployment.

## Costs

Model calls so far: a handful of requests on `gpt-5-4-mini`. Hosted agent: one session, 0.5 vCPU,
15-minute idle timeout (default). Registry: Basic tier. All within the 50 EUR budget alert.
