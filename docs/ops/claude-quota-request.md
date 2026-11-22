# Claude quota request (Azure support ticket)

Status 2026-11-22: every Anthropic Claude model shows 0 TPM quota in the subscription. The deployment of
`claude-haiku-5-5` fails preflight with `InsufficientQuota` (tracking id <tracking id>).
Microsoft staff on Q&A say the standard quota form is not enough when starting from zero; a support
ticket is required. The support API needs a paid plan, so the ticket is opened in the portal (Basic plan
allows quota tickets).

## Where

Azure portal → **Help + support** → **Create a support request**

| Field | Value |
|---|---|
| Issue type | Technical |
| Subscription | MCPP Subscription |
| Service | Microsoft Foundry |
| Resource | `aif-pvsweep-dev-3kk4ld` (resource group `rg-pvsweep-dev`) |
| Problem type | Anthropic models |
| Problem subtype | Billing or quota issues |
| Severity | C – Minimal impact |
| Preferred contact | Email |

If the portal routes quota requests through *Service and subscription limits (quotas)* → *Cognitive Services*
instead, use that path with the same text.

## Title

```
Initial quota allocation for Anthropic Claude models (claude-haiku-5-5, claude-sonnet-5-5) in Sweden Central
```

## Description

```
Request for initial quota allocation (Global Standard enablement) for Anthropic Claude models in Microsoft Foundry.

Subscription: MCPP Subscription (pay-as-you-go, billing country Spain). Region: Sweden Central.
Foundry resource: aif-pvsweep-dev-3kk4ld (resource group rg-pvsweep-dev).

Models and requested quota (Global Standard, model version 2 = Hosted on Azure):
- claude-haiku-5-5: 40K tokens per minute
- claude-sonnet-5-5: 40K tokens per minute

Current state: every Anthropic Claude model shows 0 TPM quota in this subscription (az cognitiveservices
usage list, Sweden Central). A Bicep deployment of claude-haiku-5-5 with capacity 10 failed preflight
validation with InsufficientQuota: "The deployment requires 10 quota units, but only 0 quota units are
available in Tokens Per Minute (thousands) - Claude Haiku 5.5. Current usage: 0 / 0."
Tracking id <tracking id>. The deployment includes modelProviderData
(organizationName, countryCode ES, industry) for the Azure Marketplace offer.

Use case: a pharmacovigilance proof of concept (adverse-event screening and matching) that compares GPT
and Claude models on identical evaluations. Expected usage is well under 40K TPM per model. Global Standard
is the only deployment type offered for Claude in Sweden Central.

Please enable the initial Global Standard quota for the two models above, or advise if a different process
applies to pay-as-you-go subscriptions.
```

## Also to request (same ticket or a second one)

`gpt-5.5` has 0 TPM quota as EU Data Zone Standard in Sweden Central. Request 50K TPM for
`gpt-5.5` (DataZoneStandard) for the same proof of concept, or we substitute another large GPT model
that already has quota.

## Ticket

| | |
|---|---|
| Support ticket id | **<ticket id>** |
| Opened | 2026-11-22 14:35 UTC, status Open, severity C (minimal) |
| Path used | Issue type *Service and subscription limits (quotas)* → quota type *Cognitive Services* (the Basic plan allows this path; the *Technical → Anthropic models* path requires a paid plan) |
| Contents | Claude Haiku 5.5 and Sonnet 5.5 at 40K TPM (Global Standard, version 2) and gpt-5.5 at 50K TPM (EU Data Zone Standard), Sweden Central |
| Check status | `az support in-subscription tickets show --ticket-name <ticket name>` |

## After the ticket When quota arrives, set `claudeSmallModel` back to `claude-haiku-5-5`
in `infra/main.parameters.local.json` and run `make deploy`.
