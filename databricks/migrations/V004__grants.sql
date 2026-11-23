-- V004: grants. Port of snowflake/migrations/V004__grants.sql; Snowflake roles are Databricks account
-- groups with the same names (created, and filled, outside SQL: see databricks/bootstrap.sql).
--
-- Mapping:
--   USAGE ON DATABASE                         -> USE CATALOG
--   USAGE ON SCHEMA                           -> USE SCHEMA
--   SELECT ON ALL + FUTURE TABLES/VIEWS       -> SELECT ON SCHEMA (Unity Catalog privileges granted on a
--                                                schema apply to its current and future tables and views;
--                                                there are no FUTURE grants)
--   INSERT ON ALL + FUTURE TABLES             -> MODIFY ON SCHEMA
--   READ, WRITE ON STAGE OPS.LOAD_STAGE       -> READ VOLUME, WRITE VOLUME ON VOLUME OPS.LOAD_STAGE
--   GRANT ROLE PVSWEEP_PIPELINE/AGENT TO CI   -> the same privileges granted to PVSWEEP_CI directly
--
-- Gap: Unity Catalog has no INSERT-only privilege. MODIFY also allows UPDATE and DELETE, so the rule
-- "run-time roles never get UPDATE or DELETE on SWEEP, REVIEW or AUDIT" is not enforced by these grants
-- (see databricks/README.md for the delta.appendOnly option).

GRANT USE CATALOG ON CATALOG ${catalog} TO `${pvsweep_pipeline}`;
GRANT USE CATALOG ON CATALOG ${catalog} TO `${pvsweep_agent}`;
GRANT USE CATALOG ON CATALOG ${catalog} TO `${pvsweep_review_app}`;
GRANT USE CATALOG ON CATALOG ${catalog} TO `${pvsweep_reviewer}`;
GRANT USE CATALOG ON CATALOG ${catalog} TO `${pvsweep_analyst}`;
GRANT USE CATALOG ON CATALOG ${catalog} TO `${pvsweep_ci}`;

-- Pipeline: read sources, write results.
GRANT USE SCHEMA ON SCHEMA ${catalog}.REF TO `${pvsweep_pipeline}`;
GRANT USE SCHEMA ON SCHEMA ${catalog}.SRC TO `${pvsweep_pipeline}`;
GRANT USE SCHEMA ON SCHEMA ${catalog}.PV TO `${pvsweep_pipeline}`;
GRANT USE SCHEMA ON SCHEMA ${catalog}.AGENT_API TO `${pvsweep_pipeline}`;
GRANT USE SCHEMA ON SCHEMA ${catalog}.SWEEP TO `${pvsweep_pipeline}`;
GRANT USE SCHEMA ON SCHEMA ${catalog}.AUDIT TO `${pvsweep_pipeline}`;
GRANT USE SCHEMA ON SCHEMA ${catalog}.EVAL TO `${pvsweep_pipeline}`;
GRANT USE SCHEMA ON SCHEMA ${catalog}.OPS TO `${pvsweep_pipeline}`;
GRANT SELECT ON SCHEMA ${catalog}.REF TO `${pvsweep_pipeline}`;
GRANT SELECT ON SCHEMA ${catalog}.SRC TO `${pvsweep_pipeline}`;
GRANT SELECT ON SCHEMA ${catalog}.PV TO `${pvsweep_pipeline}`;
GRANT SELECT ON SCHEMA ${catalog}.EVAL TO `${pvsweep_pipeline}`;
GRANT SELECT ON SCHEMA ${catalog}.AGENT_API TO `${pvsweep_pipeline}`;
GRANT SELECT ON SCHEMA ${catalog}.SWEEP TO `${pvsweep_pipeline}`;
GRANT SELECT ON SCHEMA ${catalog}.AUDIT TO `${pvsweep_pipeline}`;
GRANT MODIFY ON SCHEMA ${catalog}.SWEEP TO `${pvsweep_pipeline}`;
GRANT MODIFY ON SCHEMA ${catalog}.AUDIT TO `${pvsweep_pipeline}`;
GRANT MODIFY ON SCHEMA ${catalog}.EVAL TO `${pvsweep_pipeline}`;
GRANT READ VOLUME ON VOLUME ${catalog}.OPS.LOAD_STAGE TO `${pvsweep_pipeline}`;
GRANT WRITE VOLUME ON VOLUME ${catalog}.OPS.LOAD_STAGE TO `${pvsweep_pipeline}`;

-- Agents: the AGENT_API views only.
GRANT USE SCHEMA ON SCHEMA ${catalog}.AGENT_API TO `${pvsweep_agent}`;
GRANT SELECT ON SCHEMA ${catalog}.AGENT_API TO `${pvsweep_agent}`;

-- Review app: read what review needs, insert decisions.
GRANT USE SCHEMA ON SCHEMA ${catalog}.REF TO `${pvsweep_review_app}`;
GRANT USE SCHEMA ON SCHEMA ${catalog}.SRC TO `${pvsweep_review_app}`;
GRANT USE SCHEMA ON SCHEMA ${catalog}.PV TO `${pvsweep_review_app}`;
GRANT USE SCHEMA ON SCHEMA ${catalog}.SWEEP TO `${pvsweep_review_app}`;
GRANT USE SCHEMA ON SCHEMA ${catalog}.REVIEW TO `${pvsweep_review_app}`;
GRANT USE SCHEMA ON SCHEMA ${catalog}.AUDIT TO `${pvsweep_review_app}`;
GRANT USE SCHEMA ON SCHEMA ${catalog}.REPORT TO `${pvsweep_review_app}`;
GRANT SELECT ON SCHEMA ${catalog}.REF TO `${pvsweep_review_app}`;
GRANT SELECT ON SCHEMA ${catalog}.SRC TO `${pvsweep_review_app}`;
GRANT SELECT ON SCHEMA ${catalog}.PV TO `${pvsweep_review_app}`;
GRANT SELECT ON SCHEMA ${catalog}.SWEEP TO `${pvsweep_review_app}`;
GRANT SELECT ON SCHEMA ${catalog}.REVIEW TO `${pvsweep_review_app}`;
GRANT SELECT ON SCHEMA ${catalog}.AUDIT TO `${pvsweep_review_app}`;
GRANT SELECT ON SCHEMA ${catalog}.REPORT TO `${pvsweep_review_app}`;
GRANT MODIFY ON SCHEMA ${catalog}.REVIEW TO `${pvsweep_review_app}`;

-- Analysts: report views only.
GRANT USE SCHEMA ON SCHEMA ${catalog}.REPORT TO `${pvsweep_analyst}`;
GRANT SELECT ON SCHEMA ${catalog}.REPORT TO `${pvsweep_analyst}`;

-- CI: like pipeline plus agent. Snowflake nests the roles (GRANT ROLE ... TO ROLE PVSWEEP_CI); here the
-- same privileges are granted directly, so they stay visible in SQL. The right to create a CI catalog is
-- granted in databricks/bootstrap.sql.
GRANT USE SCHEMA ON SCHEMA ${catalog}.REF TO `${pvsweep_ci}`;
GRANT USE SCHEMA ON SCHEMA ${catalog}.SRC TO `${pvsweep_ci}`;
GRANT USE SCHEMA ON SCHEMA ${catalog}.PV TO `${pvsweep_ci}`;
GRANT USE SCHEMA ON SCHEMA ${catalog}.AGENT_API TO `${pvsweep_ci}`;
GRANT USE SCHEMA ON SCHEMA ${catalog}.SWEEP TO `${pvsweep_ci}`;
GRANT USE SCHEMA ON SCHEMA ${catalog}.AUDIT TO `${pvsweep_ci}`;
GRANT USE SCHEMA ON SCHEMA ${catalog}.EVAL TO `${pvsweep_ci}`;
GRANT USE SCHEMA ON SCHEMA ${catalog}.OPS TO `${pvsweep_ci}`;
GRANT SELECT ON SCHEMA ${catalog}.REF TO `${pvsweep_ci}`;
GRANT SELECT ON SCHEMA ${catalog}.SRC TO `${pvsweep_ci}`;
GRANT SELECT ON SCHEMA ${catalog}.PV TO `${pvsweep_ci}`;
GRANT SELECT ON SCHEMA ${catalog}.EVAL TO `${pvsweep_ci}`;
GRANT SELECT ON SCHEMA ${catalog}.AGENT_API TO `${pvsweep_ci}`;
GRANT SELECT ON SCHEMA ${catalog}.SWEEP TO `${pvsweep_ci}`;
GRANT SELECT ON SCHEMA ${catalog}.AUDIT TO `${pvsweep_ci}`;
GRANT MODIFY ON SCHEMA ${catalog}.SWEEP TO `${pvsweep_ci}`;
GRANT MODIFY ON SCHEMA ${catalog}.AUDIT TO `${pvsweep_ci}`;
GRANT MODIFY ON SCHEMA ${catalog}.EVAL TO `${pvsweep_ci}`;
GRANT READ VOLUME ON VOLUME ${catalog}.OPS.LOAD_STAGE TO `${pvsweep_ci}`;
GRANT WRITE VOLUME ON VOLUME ${catalog}.OPS.LOAD_STAGE TO `${pvsweep_ci}`;
