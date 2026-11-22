# Provider comparison: gpt (run-eb4b95d0299f) vs claude-direct (run-44201d1a357d)

406 records in both runs.

## All records (406 records)

| Metric | gpt | claude-direct |
|---|---|---|
| screening_recall | 0.997 | 0.991 |
| screening_precision | 1.0 | 1.0 |
| screening_class_accuracy | 0.995 | 0.988 |
| extraction_valid_share | 0.985 | 1.0 |
| causality_statement_accuracy | 0.887 | 0.927 |
| sex_accuracy | 0.991 | 0.988 |
| age_accuracy | 0.97 | 0.97 |
| seriousness_accuracy | 0.985 | 0.985 |
| event_hit_rate | 0.75 | 0.743 |
| matching_accuracy | 0.729 | 0.903 |
| matching_blocked_share | 0.006 | 0.003 |

## Records written by foundry (225 records)

| Metric | gpt | claude-direct |
|---|---|---|
| screening_recall | 1.0 | 0.995 |
| screening_precision | 1.0 | 1.0 |
| screening_class_accuracy | 0.996 | 0.996 |
| extraction_valid_share | 0.984 | 1.0 |
| causality_statement_accuracy | 0.91 | 0.953 |
| sex_accuracy | 0.995 | 0.995 |
| age_accuracy | 0.968 | 0.968 |
| seriousness_accuracy | 0.973 | 0.979 |
| event_hit_rate | 0.787 | 0.811 |
| matching_accuracy | 0.67 | 0.842 |
| matching_blocked_share | 0.005 | 0.005 |

## Records written by anthropic (181 records)

| Metric | gpt | claude-direct |
|---|---|---|
| screening_recall | 0.993 | 0.986 |
| screening_precision | 1.0 | 1.0 |
| screening_class_accuracy | 0.994 | 0.978 |
| extraction_valid_share | 0.986 | 1.0 |
| causality_statement_accuracy | 0.857 | 0.894 |
| sex_accuracy | 0.986 | 0.979 |
| age_accuracy | 0.971 | 0.972 |
| seriousness_accuracy | 1.0 | 0.993 |
| event_hit_rate | 0.7 | 0.652 |
| matching_accuracy | 0.807 | 0.986 |
| matching_blocked_share | 0.007 | 0.0 |

## Matching accuracy by scenario kind

| Kind | n | gpt | claude-direct |
|---|---|---|---|
| INCOMPLETE | 32 | 0.767 | 1.0 |
| IN_INTAKE_QUEUE | 33 | 0.939 | 1.0 |
| IN_SAFETY_DB | 24 | 0.417 | 0.391 |
| NEW_PSP_NO_CAUSALITY | 31 | 0.667 | 0.968 |
| NEW_PSP_WITH_CAUSALITY | 28 | 0.704 | 1.0 |
| NEW_SPONTANEOUS | 72 | 0.704 | 0.986 |
| NEW_SPONTANEOUS_EXCLUDED | 12 | 0.667 | 1.0 |
| NON_SIGNIFICANT_FOLLOW_UP | 8 | 0.125 | 0.625 |
| NO_PV_CONTENT | 72 | None | None |
| OTHER_MAH_PRODUCT | 23 | 0.957 | 1.0 |
| PLANNED_PROCEDURE | 22 | 0.955 | 1.0 |
| SIGNIFICANT_FOLLOW_UP | 17 | 0.412 | 0.235 |
| SPECIAL_SITUATION | 32 | 0.871 | 1.0 |

## Cost and latency (audited calls)

| Run | Step | Deployment | Calls | Input tok | Cached | Output tok | Latency avg ms | p95 ms | Failed |
|---|---|---|---|---|---|---|---|---|---|
| gpt | extract | gpt-5-4-mini | 393 | 532017 | 5120 | 136954 | 2003 | 4415 | 2 |
| gpt | match | gpt-5-4-mini | 372 | 0 | 0 | 0 | 13063 | 27163 | 2 |
| gpt | screen | gpt-5-4-mini | 450 | 380045 | 0 | 42354 | 1420 | 3141 | 0 |
| claude-direct | extract | claude-haiku-5-5 | 374 | 85372 | 1140454 | 578688 | 7270 | 10131 | 50 |
| claude-direct | extract | claude-sonnet-5-5 | 50 | 12308 | 150626 | 69351 | 9167 | 12548 | 0 |
| claude-direct | match | claude-sonnet-5-5 | 372 | 0 | 0 | 0 | 10173 | 16537 | 1 |
| claude-direct | screen | claude-haiku-5-5 | 450 | 101314 | 661560 | 124591 | 1983 | 3048 | 6 |

Estimated model cost at list prices: gpt $1.49, claude-direct $0.66 (the in-process agent's tokens are included where the framework reports them).
