-- V002: reference data, the safety database extract and the evaluation benchmarks.
-- Column names follow the loader's Parquet files (runner/pvsweep_load), so COPY INTO uses MATCH_BY_COLUMN_NAME.
USE ROLE PVSWEEP_ADMIN;
USE DATABASE PVSWEEP;

-- Where every loaded dataset came from, with licence and the date offset applied.
CREATE TABLE IF NOT EXISTS REF.DATA_SOURCE (
  target_table      STRING NOT NULL,
  dataset           STRING,
  revision          STRING,
  licence           STRING,
  attribution       STRING,
  row_count         NUMBER,
  date_offset_days  NUMBER,
  reference_date    DATE,
  loaded_at         TIMESTAMP_TZ
);

-- Contoso Pharma's portfolio: fictional brands over real active substances.
CREATE TABLE IF NOT EXISTS REF.PRODUCT (
  substance   STRING NOT NULL,
  brand       STRING NOT NULL,
  atc_code    STRING,
  CONSTRAINT pk_product PRIMARY KEY (substance)
);

CREATE TABLE IF NOT EXISTS REF.CHANNEL (
  channel_code   STRING NOT NULL,   -- MI | CRM | PSP | PQC | SOCIAL
  channel_name   STRING NOT NULL,
  report_type    STRING NOT NULL,   -- spontaneous | solicited
  operated_by    STRING NOT NULL,   -- MAH | vendor
  vendor_code    STRING,
  CONSTRAINT pk_channel PRIMARY KEY (channel_code)
);

CREATE TABLE IF NOT EXISTS REF.VENDOR (
  vendor_code                 STRING NOT NULL,
  vendor_name                 STRING NOT NULL,
  forwarding_business_days    NUMBER NOT NULL,   -- SDEA timeline for forwarding safety information to PV
  CONSTRAINT pk_vendor PRIMARY KEY (vendor_code)
);

-- Demo-mode term vocabulary (not MedDRA): PT names seen in the public datasets.
CREATE TABLE IF NOT EXISTS REF.PT_VOCAB (
  pt_name       STRING NOT NULL,
  occurrences   NUMBER
);

-- Important Medical Event terms: bring-your-own EMA file, or the project's short demo list.
CREATE TABLE IF NOT EXISTS REF.IME_TERM (
  pt_name   STRING NOT NULL,
  source    STRING NOT NULL   -- 'EMA IME list <version>' | 'demo list'
);

-- Safety database extract (FAERS-derived, EU/EEA, portfolio substances, dates shifted).
CREATE TABLE IF NOT EXISTS PV.SAFETY_CASE (
  case_id                     STRING NOT NULL,
  source_case_id              STRING,
  case_version                NUMBER,
  initial_receipt_date        DATE,
  latest_receipt_date         DATE,
  event_date                  DATE,
  report_kind                 STRING,
  reporter_type               STRING,
  age_years                   FLOAT,
  sex                         STRING,
  occurrence_country          STRING,
  reporter_country            STRING,
  serious                     BOOLEAN,
  death                       BOOLEAN,
  life_threatening            BOOLEAN,
  hospitalisation             BOOLEAN,
  disability                  BOOLEAN,
  congenital_anomaly          BOOLEAN,
  other_medically_important   BOOLEAN,
  CONSTRAINT pk_safety_case PRIMARY KEY (case_id)
);

CREATE TABLE IF NOT EXISTS PV.CASE_DRUG (
  case_id             STRING NOT NULL,
  drug_seq            NUMBER,
  role                STRING,
  substance           STRING,
  product_name        STRING,
  ownership           STRING,
  active_ingredient   STRING,
  route               STRING,
  dose_verbatim       STRING,
  lot_num             STRING,
  start_date          DATE,
  end_date            DATE
);

CREATE TABLE IF NOT EXISTS PV.CASE_EVENT (
  case_id                 STRING NOT NULL,
  pt                      STRING NOT NULL,
  dechallenge_recovery    STRING
);

CREATE TABLE IF NOT EXISTS PV.CASE_INDICATION (
  case_id         STRING NOT NULL,
  drug_seq        NUMBER,
  indication_pt   STRING
);

-- Version history of the scenario cases (synthetic; FAERS keeps only the latest version).
CREATE TABLE IF NOT EXISTS PV.CASE_VERSION (
  case_id               STRING NOT NULL,
  case_version          NUMBER NOT NULL,
  received_date         DATE NOT NULL,
  significant           BOOLEAN NOT NULL,
  information_summary   STRING,
  CONSTRAINT pk_case_version PRIMARY KEY (case_id, case_version)
);

-- PV intake queue and log, and the vendor transmission log (synthetic).
CREATE TABLE IF NOT EXISTS PV.INTAKE_QUEUE (
  intake_id        STRING NOT NULL,
  channel_code     STRING,
  vendor_reference STRING,
  received_by_pv   TIMESTAMP_NTZ,
  status           STRING,            -- pending | processed | rejected
  case_id          STRING,
  summary          STRING,
  CONSTRAINT pk_intake_queue PRIMARY KEY (intake_id)
);

CREATE TABLE IF NOT EXISTS PV.INTAKE_LOG (
  intake_id         STRING NOT NULL,
  vendor_code       STRING,
  vendor_reference  STRING,
  received_by_pv    TIMESTAMP_NTZ,
  product_name      STRING,
  event_summary     STRING
);

CREATE TABLE IF NOT EXISTS PV.VENDOR_TX_LOG (
  vendor_code       STRING NOT NULL,
  vendor_reference  STRING NOT NULL,
  sent_at           TIMESTAMP_NTZ,
  product_name      STRING,
  event_summary     STRING,
  CONSTRAINT pk_vendor_tx PRIMARY KEY (vendor_code, vendor_reference)
);

-- VAERS benchmarks (real text, vaccines; separate track).
CREATE TABLE IF NOT EXISTS EVAL.VAERS_CODING (
  benchmark_id   STRING NOT NULL,
  age_years      FLOAT,
  sex            STRING,
  vaccine        STRING,
  symptom_pts    ARRAY,
  narrative      STRING,
  CONSTRAINT pk_vaers_coding PRIMARY KEY (benchmark_id)
);

CREATE TABLE IF NOT EXISTS EVAL.VAERS_OUTCOMES (
  benchmark_id      STRING NOT NULL,
  narrative         STRING,
  outcome_label     STRING,
  hospitalisation   BOOLEAN,
  death             BOOLEAN,
  CONSTRAINT pk_vaers_outcomes PRIMARY KEY (benchmark_id)
);
