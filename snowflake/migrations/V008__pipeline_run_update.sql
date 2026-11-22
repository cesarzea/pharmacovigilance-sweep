-- V008: the runner closes its own run header (finished_at, counts, cost, status). UPDATE on that one
-- table is the only write-back a run-time role gets; results and audit rows stay insert-only.
USE ROLE PVSWEEP_ADMIN;
USE DATABASE PVSWEEP;

GRANT UPDATE ON TABLE SWEEP.RUN TO ROLE PVSWEEP_PIPELINE;
