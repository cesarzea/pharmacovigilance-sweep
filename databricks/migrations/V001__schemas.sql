-- V001: schemas, migration history and the loading volume. Run by a member of PVSWEEP_ADMIN
-- (scripts/dbx_migrate.py applies migrations in order). Port of snowflake/migrations/V001__schemas.sql.
-- Every name is fully qualified: each Statement Execution API call is its own session, so USE CATALOG
-- would not carry over to the next statement.

CREATE SCHEMA IF NOT EXISTS ${catalog}.REF       COMMENT 'Reference data: products, channels, vendors, vocabulary, configuration';
CREATE SCHEMA IF NOT EXISTS ${catalog}.SRC       COMMENT 'Source records from the non-PV channels';
CREATE SCHEMA IF NOT EXISTS ${catalog}.PV        COMMENT 'Safety database extract, PV intake queue and log, vendor transmission log';
CREATE SCHEMA IF NOT EXISTS ${catalog}.AGENT_API COMMENT 'Views read by the hosted matching agents';
CREATE SCHEMA IF NOT EXISTS ${catalog}.SWEEP     COMMENT 'Runs, screening, extraction, rules, matching, findings';
CREATE SCHEMA IF NOT EXISTS ${catalog}.REVIEW    COMMENT 'Reviewer decisions, follow-ups, case intake packages, deviations, CAPAs';
CREATE SCHEMA IF NOT EXISTS ${catalog}.AUDIT     COMMENT 'One row per model call and agent invocation';
CREATE SCHEMA IF NOT EXISTS ${catalog}.EVAL      COMMENT 'Gold labels, benchmarks, evaluation references';
CREATE SCHEMA IF NOT EXISTS ${catalog}.REPORT    COMMENT 'Reconciliation and KPI views';
CREATE SCHEMA IF NOT EXISTS ${catalog}.OPS       COMMENT 'Migration history and loading volume';

-- Column defaults on Delta tables need the allowColumnDefaults table feature.
CREATE TABLE IF NOT EXISTS ${catalog}.OPS.MIGRATION (
  version     STRING NOT NULL,
  applied_at  TIMESTAMP DEFAULT current_timestamp(),
  CONSTRAINT pk_migration PRIMARY KEY (version)
) TBLPROPERTIES ('delta.feature.allowColumnDefaults' = 'supported');

-- Snowflake: CREATE STAGE OPS.LOAD_STAGE FILE_FORMAT = (TYPE = PARQUET).
CREATE VOLUME IF NOT EXISTS ${catalog}.OPS.LOAD_STAGE COMMENT 'Staged Parquet files from the loader';
