-- Pharmacovigilance Sweep: one-time bootstrap. Run once as ACCOUNTADMIN:
--
--   snow sql -c <admin-connection> -f snowflake/bootstrap/bootstrap.sql \
--     -D runner_public_key='<RSA public key, PEM body without header lines>' \
--     -D agent_public_key='<RSA public key, PEM body without header lines>'
--
-- Creates roles, warehouse, database and service users. Everything else is in snowflake/migrations.
-- Keys come from `make snow-keys`; the private keys go to Key Vault and a Foundry connection, never here.

USE ROLE ACCOUNTADMIN;

CREATE ROLE IF NOT EXISTS PVSWEEP_ADMIN      COMMENT = 'Owns PVSWEEP objects; deployment only';
CREATE ROLE IF NOT EXISTS PVSWEEP_PIPELINE   COMMENT = 'Sweep runner: reads sources, writes results and audit';
CREATE ROLE IF NOT EXISTS PVSWEEP_AGENT      COMMENT = 'Hosted matching agents: AGENT_API views only';
CREATE ROLE IF NOT EXISTS PVSWEEP_REVIEW_APP COMMENT = 'Owner of the Streamlit review app';
CREATE ROLE IF NOT EXISTS PVSWEEP_REVIEWER   COMMENT = 'PV reviewers: review app, unmasked patient fields';
CREATE ROLE IF NOT EXISTS PVSWEEP_ANALYST    COMMENT = 'Report views only, masked';
CREATE ROLE IF NOT EXISTS PVSWEEP_CI         COMMENT = 'CI: pipeline and agent rights on a cloned database';

GRANT ROLE PVSWEEP_ADMIN TO ROLE SYSADMIN;
GRANT ROLE PVSWEEP_PIPELINE, PVSWEEP_AGENT, PVSWEEP_REVIEW_APP, PVSWEEP_REVIEWER, PVSWEEP_ANALYST, PVSWEEP_CI
  TO ROLE PVSWEEP_ADMIN;

CREATE WAREHOUSE IF NOT EXISTS PVSWEEP_WH
  WAREHOUSE_SIZE = XSMALL AUTO_SUSPEND = 60 AUTO_RESUME = TRUE INITIALLY_SUSPENDED = TRUE
  COMMENT = 'Pharmacovigilance Sweep';
GRANT USAGE, OPERATE ON WAREHOUSE PVSWEEP_WH TO ROLE PVSWEEP_ADMIN;
GRANT USAGE ON WAREHOUSE PVSWEEP_WH TO ROLE PVSWEEP_PIPELINE, ROLE PVSWEEP_AGENT, ROLE PVSWEEP_REVIEW_APP,
  ROLE PVSWEEP_REVIEWER, ROLE PVSWEEP_ANALYST, ROLE PVSWEEP_CI;

CREATE DATABASE IF NOT EXISTS PVSWEEP COMMENT = 'Pharmacovigilance Sweep';
GRANT OWNERSHIP ON DATABASE PVSWEEP TO ROLE PVSWEEP_ADMIN COPY CURRENT GRANTS;
GRANT CREATE DATABASE ON ACCOUNT TO ROLE PVSWEEP_CI;   -- zero-copy clones for evaluation runs

-- Service users: key-pair authentication only, no passwords.
CREATE USER IF NOT EXISTS PVSWEEP_RUNNER
  TYPE = SERVICE DEFAULT_ROLE = PVSWEEP_PIPELINE DEFAULT_WAREHOUSE = PVSWEEP_WH
  RSA_PUBLIC_KEY = '&{runner_public_key}' COMMENT = 'Sweep runner (Azure Container Apps job)';
GRANT ROLE PVSWEEP_PIPELINE TO USER PVSWEEP_RUNNER;

CREATE USER IF NOT EXISTS PVSWEEP_AGENT
  TYPE = SERVICE DEFAULT_ROLE = PVSWEEP_AGENT DEFAULT_WAREHOUSE = PVSWEEP_WH
  RSA_PUBLIC_KEY = '&{agent_public_key}' COMMENT = 'Hosted matching agents (Foundry Agent Service)';
GRANT ROLE PVSWEEP_AGENT TO USER PVSWEEP_AGENT;

-- The engineer who runs migrations works with PVSWEEP_ADMIN.
GRANT ROLE PVSWEEP_ADMIN TO USER IDENTIFIER(CURRENT_USER());
