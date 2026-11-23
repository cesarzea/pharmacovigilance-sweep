-- V008: the runner closes its own run header (finished_at, counts, cost, status). Port of
-- snowflake/migrations/V008__pipeline_run_update.sql, where UPDATE on SWEEP.RUN is the only write-back a
-- run-time role gets. Unity Catalog has no UPDATE-only privilege: MODIFY covers INSERT, UPDATE and DELETE,
-- and PVSWEEP_PIPELINE already holds MODIFY on schema SWEEP (V004), so this grant adds no right. It is kept
-- so the intent stays visible and survives if V004 is ever narrowed to table-level grants.

GRANT MODIFY ON TABLE ${catalog}.SWEEP.RUN TO `${pvsweep_pipeline}`;
