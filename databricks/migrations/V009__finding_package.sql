-- V009: the runner writes the prioritised findings itself (runner/pvsweep_runner/findings.py): a one-line
-- summary, a note for records that need manual work, and the proposed case intake package for potential
-- cases. Port of snowflake/migrations/V009__finding_package.sql; the schema-level grants cover the new
-- columns.
-- Databricks has no ADD COLUMN IF NOT EXISTS. Each column is its own statement, and the @ignore-error
-- annotation tells scripts/dbx_migrate.py to treat "column already exists" as done, so a re-run after a
-- partial failure is safe. Any other error still fails the migration.

-- @ignore-error FIELD_ALREADY_EXISTS, FIELDS_ALREADY_EXISTS, DELTA_DUPLICATE_COLUMNS_FOUND
ALTER TABLE ${catalog}.SWEEP.FINDING ADD COLUMNS (summary STRING);

-- @ignore-error FIELD_ALREADY_EXISTS, FIELDS_ALREADY_EXISTS, DELTA_DUPLICATE_COLUMNS_FOUND
ALTER TABLE ${catalog}.SWEEP.FINDING ADD COLUMNS (note STRING);

-- Proposed case intake package (JSON). On a warehouse without VARIANT support the type must be STRING
-- and the SET TBLPROPERTIES statement must be dropped.
-- A table created without a VARIANT column needs the variant table feature enabled before one can be
-- added (CREATE TABLE enables it automatically, ADD COLUMNS does not). Setting it again is a no-op.
ALTER TABLE ${catalog}.SWEEP.FINDING SET TBLPROPERTIES ('delta.feature.variantType-preview' = 'supported');

-- @ignore-error FIELD_ALREADY_EXISTS, FIELDS_ALREADY_EXISTS, DELTA_DUPLICATE_COLUMNS_FOUND
ALTER TABLE ${catalog}.SWEEP.FINDING ADD COLUMNS (package VARIANT);
