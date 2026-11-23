-- Load the staged Parquet files (data/stage) into Databricks. Port of snowflake/load/load_stage.sql.
-- scripts/dbx_load.py uploads data/stage/*.parquet to the volume /Volumes/${catalog}/ops/load_stage
-- and then runs this file. Loads are full replacements of the reference, safety-database and benchmark
-- tables, as in Snowflake (TRUNCATE, then COPY INTO; REF.DATA_SOURCE is emptied and reloaded).
--
-- Notes on COPY INTO:
--   * COPY INTO remembers which files it loaded into a table, even across TRUNCATE, and silently skips
--     them on the next run. 'force' = 'true' reloads them every time.
--   * Each COPY selects every column with an explicit cast (Snowflake: MATCH_BY_COLUMN_NAME): the Parquet
--     types are narrower or different from the table types (int32 drug_seq and case_version, double
--     occurrences, null-typed vendor_reference and case_id in intake_queue, no loaded_at in source_record).
--   * Timestamps: DuckDB writes microsecond TIMESTAMP columns without a time zone. Spark reads them
--     correctly as TIMESTAMP_NTZ (no nanosecond misreading, which is why Snowflake needed
--     USE_LOGICAL_TYPE = TRUE). A plain CAST to TIMESTAMP would interpret the wall-clock value in the
--     session time zone; appending 'Z' pins it to UTC whatever the warehouse time zone is.
--     data_source.loaded_at is already a UTC-adjusted timestamp and is cast directly.

TRUNCATE TABLE ${catalog}.PV.SAFETY_CASE;
TRUNCATE TABLE ${catalog}.PV.CASE_DRUG;
TRUNCATE TABLE ${catalog}.PV.CASE_EVENT;
TRUNCATE TABLE ${catalog}.PV.CASE_INDICATION;
TRUNCATE TABLE ${catalog}.EVAL.VAERS_CODING;
TRUNCATE TABLE ${catalog}.EVAL.VAERS_OUTCOMES;
TRUNCATE TABLE ${catalog}.REF.PT_VOCAB;
TRUNCATE TABLE ${catalog}.SRC.SOURCE_RECORD;
TRUNCATE TABLE ${catalog}.EVAL.GOLD_RECORD;
TRUNCATE TABLE ${catalog}.PV.INTAKE_QUEUE;
TRUNCATE TABLE ${catalog}.PV.INTAKE_LOG;
TRUNCATE TABLE ${catalog}.PV.VENDOR_TX_LOG;
TRUNCATE TABLE ${catalog}.PV.CASE_VERSION;
DELETE FROM ${catalog}.REF.DATA_SOURCE;

COPY INTO ${catalog}.PV.SAFETY_CASE FROM (
  SELECT CAST(case_id AS STRING) AS case_id, CAST(source_case_id AS STRING) AS source_case_id,
         CAST(patient_initials AS STRING) AS patient_initials, CAST(case_version AS BIGINT) AS case_version,
         CAST(initial_receipt_date AS DATE) AS initial_receipt_date, CAST(latest_receipt_date AS DATE) AS latest_receipt_date,
         CAST(event_date AS DATE) AS event_date, CAST(report_kind AS STRING) AS report_kind,
         CAST(reporter_type AS STRING) AS reporter_type, CAST(age_years AS DOUBLE) AS age_years,
         CAST(sex AS STRING) AS sex, CAST(occurrence_country AS STRING) AS occurrence_country,
         CAST(reporter_country AS STRING) AS reporter_country, CAST(serious AS BOOLEAN) AS serious,
         CAST(death AS BOOLEAN) AS death, CAST(life_threatening AS BOOLEAN) AS life_threatening,
         CAST(hospitalisation AS BOOLEAN) AS hospitalisation, CAST(disability AS BOOLEAN) AS disability,
         CAST(congenital_anomaly AS BOOLEAN) AS congenital_anomaly,
         CAST(other_medically_important AS BOOLEAN) AS other_medically_important
  FROM '/Volumes/${catalog}/ops/load_stage'
) FILEFORMAT = PARQUET FILES = ('safety_case.parquet')
  FORMAT_OPTIONS ('mergeSchema' = 'false') COPY_OPTIONS ('mergeSchema' = 'false', 'force' = 'true');

COPY INTO ${catalog}.PV.CASE_DRUG FROM (
  SELECT CAST(case_id AS STRING) AS case_id, CAST(drug_seq AS BIGINT) AS drug_seq, CAST(role AS STRING) AS role,
         CAST(substance AS STRING) AS substance, CAST(product_name AS STRING) AS product_name,
         CAST(ownership AS STRING) AS ownership, CAST(active_ingredient AS STRING) AS active_ingredient,
         CAST(route AS STRING) AS route, CAST(dose_verbatim AS STRING) AS dose_verbatim,
         CAST(lot_num AS STRING) AS lot_num, CAST(start_date AS DATE) AS start_date, CAST(end_date AS DATE) AS end_date
  FROM '/Volumes/${catalog}/ops/load_stage'
) FILEFORMAT = PARQUET FILES = ('case_drug.parquet')
  FORMAT_OPTIONS ('mergeSchema' = 'false') COPY_OPTIONS ('mergeSchema' = 'false', 'force' = 'true');

COPY INTO ${catalog}.PV.CASE_EVENT FROM (
  SELECT CAST(case_id AS STRING) AS case_id, CAST(pt AS STRING) AS pt,
         CAST(dechallenge_recovery AS STRING) AS dechallenge_recovery
  FROM '/Volumes/${catalog}/ops/load_stage'
) FILEFORMAT = PARQUET FILES = ('case_event.parquet')
  FORMAT_OPTIONS ('mergeSchema' = 'false') COPY_OPTIONS ('mergeSchema' = 'false', 'force' = 'true');

COPY INTO ${catalog}.PV.CASE_INDICATION FROM (
  SELECT CAST(case_id AS STRING) AS case_id, CAST(drug_seq AS BIGINT) AS drug_seq,
         CAST(indication_pt AS STRING) AS indication_pt
  FROM '/Volumes/${catalog}/ops/load_stage'
) FILEFORMAT = PARQUET FILES = ('case_indication.parquet')
  FORMAT_OPTIONS ('mergeSchema' = 'false') COPY_OPTIONS ('mergeSchema' = 'false', 'force' = 'true');

COPY INTO ${catalog}.EVAL.VAERS_CODING FROM (
  SELECT CAST(benchmark_id AS STRING) AS benchmark_id, CAST(age_years AS DOUBLE) AS age_years,
         CAST(sex AS STRING) AS sex, CAST(vaccine AS STRING) AS vaccine,
         CAST(symptom_pts AS ARRAY<STRING>) AS symptom_pts, CAST(narrative AS STRING) AS narrative
  FROM '/Volumes/${catalog}/ops/load_stage'
) FILEFORMAT = PARQUET FILES = ('vaers_coding.parquet')
  FORMAT_OPTIONS ('mergeSchema' = 'false') COPY_OPTIONS ('mergeSchema' = 'false', 'force' = 'true');

COPY INTO ${catalog}.EVAL.VAERS_OUTCOMES FROM (
  SELECT CAST(benchmark_id AS STRING) AS benchmark_id, CAST(narrative AS STRING) AS narrative,
         CAST(outcome_label AS STRING) AS outcome_label, CAST(hospitalisation AS BOOLEAN) AS hospitalisation,
         CAST(death AS BOOLEAN) AS death
  FROM '/Volumes/${catalog}/ops/load_stage'
) FILEFORMAT = PARQUET FILES = ('vaers_outcomes.parquet')
  FORMAT_OPTIONS ('mergeSchema' = 'false') COPY_OPTIONS ('mergeSchema' = 'false', 'force' = 'true');

-- occurrences is a double in the Parquet file; Snowflake rounds it into NUMBER(38,0).
COPY INTO ${catalog}.REF.PT_VOCAB FROM (
  SELECT CAST(pt_name AS STRING) AS pt_name, CAST(ROUND(occurrences) AS BIGINT) AS occurrences
  FROM '/Volumes/${catalog}/ops/load_stage'
) FILEFORMAT = PARQUET FILES = ('pt_vocab.parquet')
  FORMAT_OPTIONS ('mergeSchema' = 'false') COPY_OPTIONS ('mergeSchema' = 'false', 'force' = 'true');

-- source_record.parquet has no loaded_at; Snowflake fills it from the column default.
COPY INTO ${catalog}.SRC.SOURCE_RECORD FROM (
  SELECT CAST(record_id AS STRING) AS record_id, CAST(channel_code AS STRING) AS channel_code,
         CAST(channel_received_date AS DATE) AS channel_received_date, CAST(country AS STRING) AS country,
         CAST(vendor_code AS STRING) AS vendor_code, CAST(vendor_reference AS STRING) AS vendor_reference,
         CAST(record_text AS STRING) AS record_text, CAST(generator AS STRING) AS generator,
         current_timestamp() AS loaded_at
  FROM '/Volumes/${catalog}/ops/load_stage'
) FILEFORMAT = PARQUET FILES = ('source_record.parquet')
  FORMAT_OPTIONS ('mergeSchema' = 'false') COPY_OPTIONS ('mergeSchema' = 'false', 'force' = 'true');

COPY INTO ${catalog}.EVAL.GOLD_RECORD FROM (
  SELECT CAST(record_id AS STRING) AS record_id, CAST(kind AS STRING) AS kind, CAST(timing AS STRING) AS timing,
         CAST(gold_screening AS STRING) AS gold_screening, CAST(gold_match AS STRING) AS gold_match,
         CAST(gold_outcome AS STRING) AS gold_outcome, CAST(gold_day0 AS DATE) AS gold_day0,
         CAST(substance AS STRING) AS substance, CAST(product_name AS STRING) AS product_name,
         CAST(ownership AS STRING) AS ownership, CAST(reporter_type AS STRING) AS reporter_type,
         CAST(patient_age AS BIGINT) AS patient_age, CAST(patient_sex AS STRING) AS patient_sex,
         CAST(event_pt AS STRING) AS event_pt, CAST(serious AS BOOLEAN) AS serious,
         CAST(hospitalisation AS BOOLEAN) AS hospitalisation, CAST(causality_statement AS STRING) AS causality_statement,
         CAST(special_situation AS STRING) AS special_situation, CAST(onset_date AS DATE) AS onset_date,
         CAST(identifiable_patient AS BOOLEAN) AS identifiable_patient,
         CAST(identifiable_reporter AS BOOLEAN) AS identifiable_reporter,
         CAST(anchor_case_id AS STRING) AS anchor_case_id, CAST(anchor_intake_id AS STRING) AS anchor_intake_id
  FROM '/Volumes/${catalog}/ops/load_stage'
) FILEFORMAT = PARQUET FILES = ('gold_record.parquet')
  FORMAT_OPTIONS ('mergeSchema' = 'false') COPY_OPTIONS ('mergeSchema' = 'false', 'force' = 'true');

-- vendor_reference and case_id are all-NULL columns of Parquet type null in this file.
COPY INTO ${catalog}.PV.INTAKE_QUEUE FROM (
  SELECT CAST(intake_id AS STRING) AS intake_id, CAST(channel_code AS STRING) AS channel_code,
         CAST(vendor_reference AS STRING) AS vendor_reference,
         CAST(concat(CAST(received_by_pv AS STRING), 'Z') AS TIMESTAMP) AS received_by_pv,
         CAST(status AS STRING) AS status, CAST(case_id AS STRING) AS case_id, CAST(summary AS STRING) AS summary
  FROM '/Volumes/${catalog}/ops/load_stage'
) FILEFORMAT = PARQUET FILES = ('intake_queue.parquet')
  FORMAT_OPTIONS ('mergeSchema' = 'false') COPY_OPTIONS ('mergeSchema' = 'false', 'force' = 'true');

COPY INTO ${catalog}.PV.INTAKE_LOG FROM (
  SELECT CAST(intake_id AS STRING) AS intake_id, CAST(vendor_code AS STRING) AS vendor_code,
         CAST(vendor_reference AS STRING) AS vendor_reference,
         CAST(concat(CAST(received_by_pv AS STRING), 'Z') AS TIMESTAMP) AS received_by_pv,
         CAST(product_name AS STRING) AS product_name, CAST(event_summary AS STRING) AS event_summary
  FROM '/Volumes/${catalog}/ops/load_stage'
) FILEFORMAT = PARQUET FILES = ('intake_log.parquet')
  FORMAT_OPTIONS ('mergeSchema' = 'false') COPY_OPTIONS ('mergeSchema' = 'false', 'force' = 'true');

COPY INTO ${catalog}.PV.VENDOR_TX_LOG FROM (
  SELECT CAST(vendor_code AS STRING) AS vendor_code, CAST(vendor_reference AS STRING) AS vendor_reference,
         CAST(concat(CAST(sent_at AS STRING), 'Z') AS TIMESTAMP) AS sent_at,
         CAST(product_name AS STRING) AS product_name, CAST(event_summary AS STRING) AS event_summary
  FROM '/Volumes/${catalog}/ops/load_stage'
) FILEFORMAT = PARQUET FILES = ('vendor_tx_log.parquet')
  FORMAT_OPTIONS ('mergeSchema' = 'false') COPY_OPTIONS ('mergeSchema' = 'false', 'force' = 'true');

COPY INTO ${catalog}.PV.CASE_VERSION FROM (
  SELECT CAST(case_id AS STRING) AS case_id, CAST(case_version AS BIGINT) AS case_version,
         CAST(received_date AS DATE) AS received_date, CAST(significant AS BOOLEAN) AS significant,
         CAST(information_summary AS STRING) AS information_summary
  FROM '/Volumes/${catalog}/ops/load_stage'
) FILEFORMAT = PARQUET FILES = ('case_version.parquet')
  FORMAT_OPTIONS ('mergeSchema' = 'false') COPY_OPTIONS ('mergeSchema' = 'false', 'force' = 'true');

-- REF.DATA_SOURCE: emptied above and reloaded from the loader manifest, as in Snowflake.
COPY INTO ${catalog}.REF.DATA_SOURCE FROM (
  SELECT CAST(target_table AS STRING) AS target_table, CAST(dataset AS STRING) AS dataset,
         CAST(revision AS STRING) AS revision, CAST(licence AS STRING) AS licence,
         CAST(attribution AS STRING) AS attribution, CAST(row_count AS BIGINT) AS row_count,
         CAST(date_offset_days AS BIGINT) AS date_offset_days, CAST(reference_date AS DATE) AS reference_date,
         CAST(loaded_at AS TIMESTAMP) AS loaded_at
  FROM '/Volumes/${catalog}/ops/load_stage'
) FILEFORMAT = PARQUET FILES = ('data_source.parquet')
  FORMAT_OPTIONS ('mergeSchema' = 'false') COPY_OPTIONS ('mergeSchema' = 'false', 'force' = 'true');

-- Same report as Snowflake, plus the loaded row count next to the manifest row count.
SELECT d.target_table, d.row_count, a.loaded_rows, d.licence, d.date_offset_days
FROM ${catalog}.REF.DATA_SOURCE d
LEFT JOIN (
  SELECT 'PV.SAFETY_CASE' AS target_table, COUNT(*) AS loaded_rows FROM ${catalog}.PV.SAFETY_CASE
  UNION ALL SELECT 'PV.CASE_DRUG', COUNT(*) FROM ${catalog}.PV.CASE_DRUG
  UNION ALL SELECT 'PV.CASE_EVENT', COUNT(*) FROM ${catalog}.PV.CASE_EVENT
  UNION ALL SELECT 'PV.CASE_INDICATION', COUNT(*) FROM ${catalog}.PV.CASE_INDICATION
  UNION ALL SELECT 'EVAL.VAERS_CODING', COUNT(*) FROM ${catalog}.EVAL.VAERS_CODING
  UNION ALL SELECT 'EVAL.VAERS_OUTCOMES', COUNT(*) FROM ${catalog}.EVAL.VAERS_OUTCOMES
  UNION ALL SELECT 'REF.PT_VOCAB', COUNT(*) FROM ${catalog}.REF.PT_VOCAB
  UNION ALL SELECT 'SRC.SOURCE_RECORD', COUNT(*) FROM ${catalog}.SRC.SOURCE_RECORD
  UNION ALL SELECT 'EVAL.GOLD_RECORD', COUNT(*) FROM ${catalog}.EVAL.GOLD_RECORD
  UNION ALL SELECT 'PV.INTAKE_QUEUE', COUNT(*) FROM ${catalog}.PV.INTAKE_QUEUE
  UNION ALL SELECT 'PV.INTAKE_LOG', COUNT(*) FROM ${catalog}.PV.INTAKE_LOG
  UNION ALL SELECT 'PV.VENDOR_TX_LOG', COUNT(*) FROM ${catalog}.PV.VENDOR_TX_LOG
  UNION ALL SELECT 'PV.CASE_VERSION', COUNT(*) FROM ${catalog}.PV.CASE_VERSION
) a ON a.target_table = d.target_table
ORDER BY 1;

-- Timestamp check, rendered in UTC whatever the session time zone (to_utc_timestamp shifts the value so
-- that date_format, which formats in the session time zone, prints the UTC wall clock). Expected from the current data/stage files:
--   PV.INTAKE_LOG    2024-11-11 16:05:00 .. 2026-10-22 16:05:00
--   PV.INTAKE_QUEUE  2026-07-05 10:00:00 .. 2026-10-26 10:00:00
--   PV.VENDOR_TX_LOG 2024-11-11 16:00:00 .. 2026-11-04 16:00:00
SELECT 'PV.INTAKE_LOG' AS target_table,
       date_format(to_utc_timestamp(MIN(received_by_pv), current_timezone()), 'yyyy-MM-dd HH:mm:ss') AS min_utc,
       date_format(to_utc_timestamp(MAX(received_by_pv), current_timezone()), 'yyyy-MM-dd HH:mm:ss') AS max_utc
FROM ${catalog}.PV.INTAKE_LOG
UNION ALL
SELECT 'PV.INTAKE_QUEUE',
       date_format(to_utc_timestamp(MIN(received_by_pv), current_timezone()), 'yyyy-MM-dd HH:mm:ss'),
       date_format(to_utc_timestamp(MAX(received_by_pv), current_timezone()), 'yyyy-MM-dd HH:mm:ss')
FROM ${catalog}.PV.INTAKE_QUEUE
UNION ALL
SELECT 'PV.VENDOR_TX_LOG',
       date_format(to_utc_timestamp(MIN(sent_at), current_timezone()), 'yyyy-MM-dd HH:mm:ss'),
       date_format(to_utc_timestamp(MAX(sent_at), current_timezone()), 'yyyy-MM-dd HH:mm:ss')
FROM ${catalog}.PV.VENDOR_TX_LOG;
