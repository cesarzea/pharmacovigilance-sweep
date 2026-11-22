-- V006: source records, sweep results, review decisions, audit trail and gold labels.
-- SWEEP, REVIEW and AUDIT are append-only for run-time roles (see V004 grants).
USE ROLE PVSWEEP_ADMIN;
USE DATABASE PVSWEEP;

CREATE TABLE IF NOT EXISTS SRC.SOURCE_RECORD (
  record_id              STRING NOT NULL,
  channel_code           STRING NOT NULL,
  channel_received_date  DATE NOT NULL,
  country                STRING,
  vendor_code            STRING,
  vendor_reference       STRING,
  record_text            STRING NOT NULL,
  generator              STRING,            -- 'foundry:<deployment>' for synthetic text
  loaded_at              TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  CONSTRAINT pk_source_record PRIMARY KEY (record_id)
);

CREATE TABLE IF NOT EXISTS SWEEP.RUN (
  run_id          STRING NOT NULL,
  started_at      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  finished_at     TIMESTAMP_NTZ,
  provider        STRING NOT NULL,          -- gpt | claude
  prompt_version  STRING NOT NULL,
  code_version    STRING,
  scope           VARIANT,                  -- channels, period, record filter
  counts          VARIANT,
  cost_usd        FLOAT,
  status          STRING,                   -- running | finished | failed
  CONSTRAINT pk_run PRIMARY KEY (run_id)
);

CREATE TABLE IF NOT EXISTS SWEEP.SCREENING (
  run_id             STRING NOT NULL,
  record_id          STRING NOT NULL,
  screening_class    STRING NOT NULL,       -- ADVERSE_EVENT | SPECIAL_SITUATION | NO_PV_CONTENT | BLOCKED | INVALID
  criteria_patient   BOOLEAN,
  criteria_reporter  BOOLEAN,
  criteria_product   BOOLEAN,
  criteria_event     BOOLEAN,
  evidence           VARIANT,               -- spans quoted from the record
  confidence         STRING,
  result             VARIANT,               -- raw model output
  created_at         TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TABLE IF NOT EXISTS SWEEP.EXTRACTION (
  run_id        STRING NOT NULL,
  record_id     STRING NOT NULL,
  result        VARIANT NOT NULL,           -- follows prompts/extraction.schema.json
  valid         BOOLEAN,
  problems      VARIANT,
  model_tier    STRING,                     -- small | large (after escalation)
  created_at    TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TABLE IF NOT EXISTS SWEEP.RULE_RESULT (
  run_id                    STRING NOT NULL,
  record_id                 STRING NOT NULL,
  ownership                 STRING,          -- own_brand | substance_only | other
  substance                 STRING,
  report_type               STRING,          -- spontaneous | solicited
  causality_required        BOOLEAN,
  ime_flag                  BOOLEAN,
  serious                   BOOLEAN,
  criteria_complete         BOOLEAN,
  proposed_day0             DATE,
  regulatory_deadline       DATE,
  days_remaining            NUMBER,
  regulatory_status         STRING,          -- clock_not_started | on_time | at_risk | overdue
  forwarding_days           NUMBER,
  forwarding_status         STRING,          -- not_applicable | within_timeline | breached
  created_at                TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TABLE IF NOT EXISTS SWEEP.MATCH_CANDIDATE (
  run_id         STRING NOT NULL,
  record_id      STRING NOT NULL,
  source         STRING NOT NULL,           -- safety_db | intake_queue | vendor_log
  candidate_id   STRING NOT NULL,
  blocking_keys  VARIANT
);

CREATE TABLE IF NOT EXISTS SWEEP.MATCH_DECISION (
  run_id          STRING NOT NULL,
  record_id       STRING NOT NULL,
  outcome         STRING NOT NULL,          -- IN_SAFETY_DB | IN_INTAKE_QUEUE | SIGNIFICANT_FOLLOW_UP | NON_SIGNIFICANT_FOLLOW_UP | DUPLICATE_IN_SWEEP | NO_MATCH | BLOCKED
  matched_ids     VARIANT,
  new_facts       VARIANT,
  justification   STRING,
  confidence      STRING,
  tool_calls      VARIANT,
  agent_name      STRING,
  agent_version   STRING,
  valid           BOOLEAN,
  created_at      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TABLE IF NOT EXISTS SWEEP.FINDING (
  run_id         STRING NOT NULL,
  finding_id     STRING NOT NULL,
  record_id      STRING,
  finding_type   STRING NOT NULL,           -- potential_case | qc_sample | transmission_gap
  priority       NUMBER,
  created_at     TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  CONSTRAINT pk_finding PRIMARY KEY (finding_id)
);

CREATE TABLE IF NOT EXISTS REVIEW.DECISION (
  decision_id         STRING NOT NULL,
  finding_id          STRING NOT NULL,
  reviewer            STRING NOT NULL,
  decided_at          TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  outcome             STRING NOT NULL,      -- A_NOT_REPORTABLE | B_ALREADY_RECEIVED | C_INCOMPLETE | D_VALID_ICSR
  checklist           VARIANT,
  confirmed_day0      DATE,
  rationale           STRING,
  supersedes_id       STRING,
  CONSTRAINT pk_decision PRIMARY KEY (decision_id)
);

CREATE TABLE IF NOT EXISTS REVIEW.FOLLOW_UP (
  follow_up_id   STRING NOT NULL,
  finding_id     STRING NOT NULL,
  addressed_to   STRING,
  missing_items  VARIANT,
  draft_text     STRING,
  sent_at        TIMESTAMP_NTZ,
  answered_at    TIMESTAMP_NTZ,
  CONSTRAINT pk_follow_up PRIMARY KEY (follow_up_id)
);

CREATE TABLE IF NOT EXISTS REVIEW.CASE_INTAKE_PACKAGE (
  package_id             STRING NOT NULL,
  finding_id             STRING NOT NULL,
  decision_id            STRING NOT NULL,
  initial_receipt_date   DATE,
  day0                   DATE,
  regulatory_deadline    DATE,
  late_submission        BOOLEAN,
  package                VARIANT,
  created_at             TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  CONSTRAINT pk_package PRIMARY KEY (package_id)
);

CREATE TABLE IF NOT EXISTS REVIEW.COMPLIANCE_FINDING (
  compliance_id   STRING NOT NULL,
  finding_id      STRING NOT NULL,
  kind            STRING NOT NULL,          -- forwarding_breach | late_submission | transmission_gap
  vendor_code     STRING,
  root_cause      STRING,                   -- not_recognised | not_forwarded | not_received | not_processed
  capa            STRING,
  created_at      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  CONSTRAINT pk_compliance PRIMARY KEY (compliance_id)
);

CREATE TABLE IF NOT EXISTS AUDIT.MODEL_CALL (
  call_id          STRING NOT NULL,
  run_id           STRING,
  record_id        STRING,
  step             STRING NOT NULL,         -- screen | extract | match | render | eval
  provider         STRING NOT NULL,
  deployment       STRING NOT NULL,
  agent_name       STRING,
  agent_version    STRING,
  prompt_version   STRING,
  schema_version   STRING,
  effort           STRING,
  input_hash       STRING,
  output_hash      STRING,
  raw_output       VARIANT,
  input_tokens     NUMBER,
  output_tokens    NUMBER,
  cached_tokens    NUMBER,
  latency_ms       NUMBER,
  status           STRING NOT NULL,         -- ok | invalid | blocked | error
  error            STRING,
  created_at       TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  CONSTRAINT pk_model_call PRIMARY KEY (call_id)
);

-- Gold labels per synthetic record (from data/synthetic/plan.json).
CREATE TABLE IF NOT EXISTS EVAL.GOLD_RECORD (
  record_id               STRING NOT NULL,
  kind                    STRING NOT NULL,
  timing                  STRING,
  gold_screening          STRING NOT NULL,
  gold_match              STRING NOT NULL,
  gold_outcome            STRING NOT NULL,
  gold_day0               DATE,
  substance               STRING,
  product_name            STRING,
  ownership               STRING,
  reporter_type           STRING,
  patient_age             NUMBER,
  patient_sex             STRING,
  event_pt                STRING,
  serious                 BOOLEAN,
  hospitalisation         BOOLEAN,
  causality_statement     STRING,
  special_situation       STRING,
  onset_date              DATE,
  identifiable_patient    BOOLEAN,
  identifiable_reporter   BOOLEAN,
  anchor_case_id          STRING,
  anchor_intake_id        STRING,
  CONSTRAINT pk_gold_record PRIMARY KEY (record_id)
);
