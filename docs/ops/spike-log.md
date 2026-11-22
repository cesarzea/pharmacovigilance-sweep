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
| 4 | Reused sessions start with fresh state | **Not tested yet.** The platform created session `0577bc8c…` on the first call (`x-agent-session-id` header); session reuse from the client is not documented and needs a test |
| 5 | Guardrail behaviour on overdose and self-harm text | **Not tested yet** |
| — | Invocations protocol end to end (`spike/02_invoke_hosted_agent.py`) | **Pass.** HTTP 200; 13.5 s for the two-probe call, 9.0 s for a trivial call. Each call without a session id got a new session (`x-agent-session-id` differs), so session reuse must be explicit |

## 2026-11-22, later: data, synthetic records, end-to-end sweep (local backend)

| Check | Result |
|---|---|
| Public data staged (`make stage-data`) | **Pass.** FAERS: 10,077 EU/EEA cases with the four substances as suspect, dates shifted by 669 days, brands remapped; VAERS: 400 coding and 400 outcome rows; vocabulary 18,470 terms. Hugging Face rate-limits DuckDB's remote reads, so files are downloaded once into `data/cache/` |
| Scenario plan (`pvsweep_synth plan`) | **Pass.** 450 scenarios over 13 kinds and 5 channels; 93 anchored on real FAERS cases; intake queue 33, intake log 85, vendor log 135 rows. Deterministic for the seed; every rendered text carries a hash of its scenario |
| Text rendering with GPT (`pvsweep_synth render --share 1/2`) | **Pass.** 225 records, 223 validated at the first attempt; about 1,200 tokens per record including retries. Claude's half waits on a working Anthropic key (the key authenticates but every call returns 429 with no rate-limit headers: account-side limit to check in the Console) |
| Sweep, 40 records, GPT, agent matching in-process | **Pass.** Screening recall 1.000 (33/33 routed, 0 false positives on 7 non-PV records). Extraction valid 33/33, 2 escalations; causality statement 30/33, sex 31/33, age 31/33. Rules: ownership 33/33; seriousness 26/33 (the misses are "other medically important" events that need the IME list, e.g. syncope). Matching 30/33 (0.909): one BLOCKED, two confusions between "already in the safety database" and "non-significant follow-up". 250 s wall-clock at concurrency 3; 75 audited model calls, about $0.13 for screening and extraction (the agent's calls are not yet audited in-process) |
| Report views (`V007`) on the local backend | **Pass.** Reconciliation finds 20 PSP, 27 MI-vendor and 3 social-listening items sent but never received, as planted |
| Foundry custom evaluators | see below |

Two things changed the matching accuracy from 0.71 to 0.91 between the first and second runs:
a stricter instruction (a lookalike with the same substance, sex and event is not a match unless
country and dates agree) and country plus receipt dates in the candidate keys. The first run also
showed that anchored scenarios need dates consistent with their case, which the planner now does.

## Facts learned

- **Anthropic API keys and workspaces:** an organisation-level key must send `anthropic-workspace-id`;
  without it the API answers 400, and a key with no credit attached answers 429 `rate_limit_error`
  with no rate-limit headers. The "Claude Code" workspace that Claude Code creates cannot be used for
  API calls (404 on messages). The runner reads `ANTHROPIC_WORKSPACE_ID` from `.env`.

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
