-- V001: schemas. Run as PVSWEEP_ADMIN (scripts/snow_migrate.sh applies migrations in order).
USE ROLE PVSWEEP_ADMIN;
USE DATABASE PVSWEEP;

CREATE SCHEMA IF NOT EXISTS REF       COMMENT = 'Reference data: products, channels, vendors, vocabulary, configuration';
CREATE SCHEMA IF NOT EXISTS SRC       COMMENT = 'Source records from the non-PV channels';
CREATE SCHEMA IF NOT EXISTS PV        COMMENT = 'Safety database extract, PV intake queue and log, vendor transmission log';
CREATE SCHEMA IF NOT EXISTS AGENT_API COMMENT = 'Secure views read by the hosted matching agents';
CREATE SCHEMA IF NOT EXISTS SWEEP     COMMENT = 'Runs, screening, extraction, rules, matching, findings';
CREATE SCHEMA IF NOT EXISTS REVIEW    COMMENT = 'Reviewer decisions, follow-ups, case intake packages, deviations, CAPAs';
CREATE SCHEMA IF NOT EXISTS AUDIT     COMMENT = 'One row per model call and agent invocation';
CREATE SCHEMA IF NOT EXISTS EVAL      COMMENT = 'Gold labels, benchmarks, evaluation references';
CREATE SCHEMA IF NOT EXISTS REPORT    COMMENT = 'Reconciliation and KPI views';
CREATE SCHEMA IF NOT EXISTS OPS       COMMENT = 'Migration history and loading stage';

CREATE TABLE IF NOT EXISTS OPS.MIGRATION (
  version     STRING NOT NULL,
  applied_at  TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  CONSTRAINT pk_migration PRIMARY KEY (version)
);

CREATE STAGE IF NOT EXISTS OPS.LOAD_STAGE FILE_FORMAT = (TYPE = PARQUET) COMMENT = 'Staged Parquet files from the loader';
