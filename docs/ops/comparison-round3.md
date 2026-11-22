# Provider comparison: gpt (run-dc415c71681e) vs claude-direct (run-ccf8b72b3429)

450 records in both runs.

## All records (450 records)

| Metric | gpt | claude-direct |
|---|---|---|
| screening_recall | 0.997 | 0.968 |
| screening_precision | 1.0 | 1.0 |
| screening_class_accuracy | 0.987 | 0.969 |
| extraction_valid_share | 0.995 | 1.0 |
| causality_statement_accuracy | 0.901 | 0.929 |
| sex_accuracy | 0.989 | 0.989 |
| age_accuracy | 0.971 | 0.975 |
| seriousness_accuracy | 0.968 | 0.978 |
| event_hit_rate | 0.779 | 0.77 |
| matching_accuracy | 0.835 | 0.956 |
| matching_blocked_share | 0.005 | 0.006 |

## Records written by foundry (225 records)

| Metric | gpt | claude-direct |
|---|---|---|
| screening_recall | 1.0 | 0.974 |
| screening_precision | 1.0 | 1.0 |
| screening_class_accuracy | 0.996 | 0.978 |
| extraction_valid_share | 0.99 | 1.0 |
| causality_statement_accuracy | 0.91 | 0.952 |
| sex_accuracy | 0.995 | 0.995 |
| age_accuracy | 0.968 | 0.973 |
| seriousness_accuracy | 0.963 | 0.978 |
| event_hit_rate | 0.799 | 0.812 |
| matching_accuracy | 0.825 | 0.957 |
| matching_blocked_share | 0.011 | 0.005 |

## Records written by anthropic (225 records)

| Metric | gpt | claude-direct |
|---|---|---|
| screening_recall | 0.995 | 0.963 |
| screening_precision | 1.0 | 1.0 |
| screening_class_accuracy | 0.978 | 0.96 |
| extraction_valid_share | 1.0 | 1.0 |
| causality_statement_accuracy | 0.892 | 0.906 |
| sex_accuracy | 0.984 | 0.983 |
| age_accuracy | 0.973 | 0.978 |
| seriousness_accuracy | 0.973 | 0.978 |
| event_hit_rate | 0.758 | 0.728 |
| matching_accuracy | 0.844 | 0.955 |
| matching_blocked_share | 0.0 | 0.006 |

## Matching accuracy by scenario kind

| Kind | n | gpt | claude-direct |
|---|---|---|---|
| INCOMPLETE | 32 | 0.935 | 1.0 |
| IN_INTAKE_QUEUE | 33 | 0.97 | 1.0 |
| IN_SAFETY_DB | 47 | 0.447 | 0.795 |
| NEW_PSP_NO_CAUSALITY | 31 | 0.968 | 1.0 |
| NEW_PSP_WITH_CAUSALITY | 28 | 0.963 | 1.0 |
| NEW_SPONTANEOUS | 72 | 0.986 | 1.0 |
| NEW_SPONTANEOUS_EXCLUDED | 12 | 0.917 | 1.0 |
| NON_SIGNIFICANT_FOLLOW_UP | 18 | 0.333 | 0.75 |
| NO_PV_CONTENT | 72 | None | None |
| OTHER_MAH_PRODUCT | 23 | 1.0 | 1.0 |
| PLANNED_PROCEDURE | 22 | 1.0 | 0.882 |
| SIGNIFICANT_FOLLOW_UP | 28 | 0.393 | 1.0 |
| SPECIAL_SITUATION | 32 | 1.0 | 0.966 |

## Cost and latency (audited calls)

| Run | Step | Deployment | Calls | Input tok | Cached | Output tok | Latency avg ms | p95 ms | Failed |
|---|---|---|---|---|---|---|---|---|---|
| gpt | extract | gpt-5-4-mini | 385 | 523765 | 55040 | 134589 | 1865 | 3419 | 0 |
| gpt | match | gpt-5-4-mini | 375 | 0 | 0 | 0 | 13922 | 27148 | 2 |
| gpt | screen | gpt-5-4-mini | 450 | 380014 | 0 | 42046 | 1334 | 2675 | 0 |
| claude-direct | extract | claude-haiku-5-5 | 366 | 83551 | 1125084 | 567059 | 7278 | 10825 | 61 |
| claude-direct | extract | claude-sonnet-5-5 | 61 | 15280 | 187514 | 85587 | 9172 | 11677 | 0 |
| claude-direct | match | claude-sonnet-5-5 | 362 | 0 | 0 | 0 | 8641 | 11829 | 2 |
| claude-direct | screen | claude-haiku-5-5 | 450 | 101284 | 666000 | 126070 | 1958 | 3176 | 14 |

Estimated model cost at list prices: gpt $1.44, claude-direct $1.31 (the in-process agent's tokens are included where the framework reports them).
