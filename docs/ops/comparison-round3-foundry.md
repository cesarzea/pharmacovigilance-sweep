# Provider comparison: gpt (run-dc415c71681e) vs claude (run-fe888fb4684e)

450 records in both runs.

## All records (450 records)

| Metric | gpt | claude |
|---|---|---|
| screening_recall | 0.997 | 0.976 |
| screening_precision | 1.0 | 0.997 |
| screening_class_accuracy | 0.987 | 0.978 |
| extraction_valid_share | 0.995 | 1.0 |
| causality_statement_accuracy | 0.901 | 0.938 |
| sex_accuracy | 0.989 | 0.989 |
| age_accuracy | 0.971 | 0.981 |
| seriousness_accuracy | 0.968 | 0.973 |
| event_hit_rate | 0.779 | 0.757 |
| matching_accuracy | 0.835 | 0.954 |
| matching_blocked_share | 0.005 | 0.008 |

## Records written by foundry (225 records)

| Metric | gpt | claude |
|---|---|---|
| screening_recall | 1.0 | 0.979 |
| screening_precision | 1.0 | 1.0 |
| screening_class_accuracy | 0.996 | 0.982 |
| extraction_valid_share | 0.99 | 1.0 |
| causality_statement_accuracy | 0.91 | 0.952 |
| sex_accuracy | 0.995 | 0.995 |
| age_accuracy | 0.968 | 0.979 |
| seriousness_accuracy | 0.963 | 0.973 |
| event_hit_rate | 0.799 | 0.797 |
| matching_accuracy | 0.825 | 0.957 |
| matching_blocked_share | 0.011 | 0.011 |

## Records written by anthropic (225 records)

| Metric | gpt | claude |
|---|---|---|
| screening_recall | 0.995 | 0.973 |
| screening_precision | 1.0 | 0.995 |
| screening_class_accuracy | 0.978 | 0.973 |
| extraction_valid_share | 1.0 | 1.0 |
| causality_statement_accuracy | 0.892 | 0.923 |
| sex_accuracy | 0.984 | 0.984 |
| age_accuracy | 0.973 | 0.984 |
| seriousness_accuracy | 0.973 | 0.973 |
| event_hit_rate | 0.758 | 0.716 |
| matching_accuracy | 0.844 | 0.95 |
| matching_blocked_share | 0.0 | 0.006 |

## Matching accuracy by scenario kind

| Kind | n | gpt | claude |
|---|---|---|---|
| INCOMPLETE | 32 | 0.935 | 1.0 |
| IN_INTAKE_QUEUE | 33 | 0.97 | 1.0 |
| IN_SAFETY_DB | 47 | 0.447 | 0.8 |
| NEW_PSP_NO_CAUSALITY | 31 | 0.968 | 1.0 |
| NEW_PSP_WITH_CAUSALITY | 28 | 0.963 | 1.0 |
| NEW_SPONTANEOUS | 72 | 0.986 | 1.0 |
| NEW_SPONTANEOUS_EXCLUDED | 12 | 0.917 | 1.0 |
| NON_SIGNIFICANT_FOLLOW_UP | 18 | 0.333 | 0.722 |
| NO_PV_CONTENT | 72 | None | None |
| OTHER_MAH_PRODUCT | 23 | 1.0 | 0.957 |
| PLANNED_PROCEDURE | 22 | 1.0 | 1.0 |
| SIGNIFICANT_FOLLOW_UP | 28 | 0.393 | 0.964 |
| SPECIAL_SITUATION | 32 | 1.0 | 0.967 |

## Cost and latency (audited calls)

| Run | Step | Deployment | Calls | Input tok | Cached | Output tok | Latency avg ms | p95 ms | Failed |
|---|---|---|---|---|---|---|---|---|---|
| gpt | extract | gpt-5-4-mini | 385 | 523765 | 55040 | 134589 | 1865 | 3419 | 0 |
| gpt | match | gpt-5-4-mini | 375 | 0 | 0 | 0 | 13922 | 27148 | 2 |
| gpt | screen | gpt-5-4-mini | 450 | 380014 | 0 | 42046 | 1334 | 2675 | 0 |
| claude | extract | claude-haiku-5-5 | 370 | 84487 | 1137380 | 567357 | 10037 | 8991 | 50 |
| claude | extract | claude-sonnet-5-5 | 51 | 13258 | 126034 | 71496 | 19893 | 59896 | 0 |
| claude | match | claude-sonnet-5-5 | 366 | 0 | 0 | 0 | 32182 | 101614 | 3 |
| claude | screen | claude-haiku-5-5 | 450 | 101284 | 666000 | 135436 | 2051 | 3072 | 9 |

Estimated model cost at list prices: gpt $1.44, claude $1.15 (the in-process agent's tokens are included where the framework reports them).
