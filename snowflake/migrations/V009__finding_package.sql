-- V009: the runner writes the prioritised findings itself (runner/pvsweep_runner/findings.py): a one-line
-- summary, a note for records that need manual work, and the proposed case intake package for potential
-- cases. The existing table grants cover the new columns; no new grants are needed.
USE ROLE PVSWEEP_ADMIN;
USE DATABASE PVSWEEP;

ALTER TABLE SWEEP.FINDING ADD COLUMN IF NOT EXISTS summary STRING;
ALTER TABLE SWEEP.FINDING ADD COLUMN IF NOT EXISTS note STRING;
ALTER TABLE SWEEP.FINDING ADD COLUMN IF NOT EXISTS package VARIANT;   -- proposed case intake package (JSON)
