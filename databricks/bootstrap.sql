-- Pharmacovigilance Sweep on Azure Databricks: one-time bootstrap of the Unity Catalog objects.
--
--   python scripts/dbx_migrate.py --bootstrap \
--     --var runner_principal=<runner service principal application id> \
--     --var agent_principal=<agent service principal application id>
--
-- Run as a member of PVSWEEP_ADMIN who holds CREATE CATALOG on the metastore; the CREATE CATALOG ON
-- METASTORE grant to PVSWEEP_CI below also needs a metastore admin. Migrations must then run as a member
-- of PVSWEEP_ADMIN too, because the schemas are owned by that group after this file.
-- The account groups must exist (and be assigned to the workspace) before this runs, or the first GRANT
-- fails with a principal-not-found error.
-- Placeholders are ${var}: the SQL Statement Execution API does not resolve them, so
-- scripts/dbx_migrate.py substitutes them before sending each statement (same role as the
-- &{var} variables in snowflake/bootstrap/bootstrap.sql). Defaults: catalog=pvsweep,
-- managed_location_clause empty (set it to MANAGED LOCATION 'abfss://...' when the metastore has
-- no root storage).
--
-- Grantees and owners are variables too: ${pvsweep_admin}, ${pvsweep_pipeline}, ${pvsweep_agent},
-- ${pvsweep_review_app}, ${pvsweep_reviewer}, ${pvsweep_analyst}, ${pvsweep_ci}, defaulting to the group
-- names PVSWEEP_ADMIN ... PVSWEEP_CI (defaults in scripts/dbx_migrate.py). Each is quoted with backticks,
-- so a user e-mail, a group name or a service principal application id all work. Until the account
-- groups exist, pass one principal (for example your own user) for all seven: the grants then collapse
-- onto that principal and the group separation is not in force. The group notes below assume the defaults.
--
-- Not expressible in SQL, done once outside this file (account console, SCIM, Terraform or the CLI):
--   * create the account groups PVSWEEP_ADMIN, PVSWEEP_PIPELINE, PVSWEEP_AGENT, PVSWEEP_REVIEW_APP,
--     PVSWEEP_REVIEWER, PVSWEEP_ANALYST, PVSWEEP_CI and assign them to the workspace;
--   * add the runner service principal to PVSWEEP_PIPELINE, the agent service principal to
--     PVSWEEP_AGENT, reviewers to PVSWEEP_REVIEWER, the deploying engineer to PVSWEEP_ADMIN;
--   * give every group CAN USE on the SQL warehouse (the Snowflake bootstrap granted USAGE on PVSWEEP_WH).
-- The last statement prints that membership checklist with the two service principal ids.

CREATE CATALOG IF NOT EXISTS ${catalog} ${managed_location_clause} COMMENT 'Pharmacovigilance Sweep';

-- Same schemas as snowflake/migrations/V001 (V001 repeats them, idempotently).
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

-- Replaces the Snowflake stage OPS.LOAD_STAGE: scripts/dbx_load.py uploads data/stage/*.parquet here.
CREATE VOLUME IF NOT EXISTS ${catalog}.OPS.LOAD_STAGE COMMENT 'Staged Parquet files from the loader';

-- PVSWEEP_ADMIN owns everything (Snowflake: GRANT OWNERSHIP ON DATABASE ... TO ROLE PVSWEEP_ADMIN).
-- ALL PRIVILEGES on the catalog is inherited by every schema, table, view and volume in it, so views
-- owned by PVSWEEP_ADMIN can read their base tables.
GRANT ALL PRIVILEGES ON CATALOG ${catalog} TO `${pvsweep_admin}`;
ALTER CATALOG ${catalog} OWNER TO `${pvsweep_admin}`;
ALTER SCHEMA ${catalog}.REF       OWNER TO `${pvsweep_admin}`;
ALTER SCHEMA ${catalog}.SRC       OWNER TO `${pvsweep_admin}`;
ALTER SCHEMA ${catalog}.PV        OWNER TO `${pvsweep_admin}`;
ALTER SCHEMA ${catalog}.AGENT_API OWNER TO `${pvsweep_admin}`;
ALTER SCHEMA ${catalog}.SWEEP     OWNER TO `${pvsweep_admin}`;
ALTER SCHEMA ${catalog}.REVIEW    OWNER TO `${pvsweep_admin}`;
ALTER SCHEMA ${catalog}.AUDIT     OWNER TO `${pvsweep_admin}`;
ALTER SCHEMA ${catalog}.EVAL      OWNER TO `${pvsweep_admin}`;
ALTER SCHEMA ${catalog}.REPORT    OWNER TO `${pvsweep_admin}`;
ALTER SCHEMA ${catalog}.OPS       OWNER TO `${pvsweep_admin}`;
ALTER VOLUME ${catalog}.OPS.LOAD_STAGE OWNER TO `${pvsweep_admin}`;

-- Snowflake: GRANT CREATE DATABASE ON ACCOUNT TO ROLE PVSWEEP_CI (zero-copy clones for evaluation runs).
-- Databricks equivalent: a CI catalog filled with SHALLOW CLONE per table. Needs a metastore admin.
GRANT CREATE CATALOG ON METASTORE TO `${pvsweep_ci}`;

-- Every other grant is in databricks/migrations/V004 (and V007, V008), as in Snowflake.

-- Group membership checklist (applied outside SQL; see the header).
SELECT * FROM VALUES
  ('${runner_principal}', '${pvsweep_pipeline}', 'Sweep runner service principal (Container Apps job)'),
  ('${agent_principal}',  '${pvsweep_agent}',   'Hosted matching agents service principal (Foundry Agent Service)')
  AS checklist(principal_application_id, add_to_group, purpose);
