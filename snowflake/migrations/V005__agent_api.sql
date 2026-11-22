-- V005: secure views for the hosted matching agents. The agent role sees nothing else.
-- Each view is the fixed query behind one agent tool; the tool only supplies parameters.
USE ROLE PVSWEEP_ADMIN;
USE DATABASE PVSWEEP;

-- Tool search_safety_cases: one row per case with the suspect products and events aggregated.
CREATE OR REPLACE SECURE VIEW AGENT_API.SAFETY_CASE_SUMMARY AS
SELECT c.case_id,
       c.patient_initials,
       c.initial_receipt_date,
       c.latest_receipt_date,
       c.event_date,
       c.case_version,
       c.reporter_type,
       c.age_years,
       c.sex,
       c.occurrence_country,
       c.serious,
       c.hospitalisation,
       c.death,
       d.substances,
       d.products,
       e.events
FROM PV.SAFETY_CASE c
LEFT JOIN (
  SELECT case_id,
         ARRAY_AGG(DISTINCT substance) WITHIN GROUP (ORDER BY substance) AS substances,
         ARRAY_AGG(DISTINCT product_name) WITHIN GROUP (ORDER BY product_name) AS products
  FROM PV.CASE_DRUG WHERE role IN ('primary_suspect', 'secondary_suspect') GROUP BY case_id
) d ON d.case_id = c.case_id
LEFT JOIN (
  SELECT case_id, ARRAY_AGG(DISTINCT pt) WITHIN GROUP (ORDER BY pt) AS events
  FROM PV.CASE_EVENT GROUP BY case_id
) e ON e.case_id = c.case_id;

-- Tool get_case_history: versions of a case with what each one added.
CREATE OR REPLACE SECURE VIEW AGENT_API.CASE_HISTORY AS
SELECT case_id, case_version, received_date, significant, information_summary
FROM PV.CASE_VERSION;

-- Tool search_intake_queue: items received by PV but not yet in the safety database.
CREATE OR REPLACE SECURE VIEW AGENT_API.INTAKE_QUEUE AS
SELECT intake_id, channel_code, vendor_reference, received_by_pv, status, case_id, summary
FROM PV.INTAKE_QUEUE;

-- Tool search_vendor_log: what vendors say they sent.
CREATE OR REPLACE SECURE VIEW AGENT_API.VENDOR_TX_LOG AS
SELECT vendor_code, vendor_reference, sent_at, product_name, event_summary
FROM PV.VENDOR_TX_LOG;

-- Reference the agent may need to normalise a brand to a substance.
CREATE OR REPLACE SECURE VIEW AGENT_API.PRODUCT AS
SELECT substance, brand FROM REF.PRODUCT;

-- Tool search_intake_log: PV's own record of what it received from a vendor.
CREATE OR REPLACE SECURE VIEW AGENT_API.INTAKE_LOG AS
SELECT intake_id, vendor_code, vendor_reference, received_by_pv, product_name, event_summary
FROM PV.INTAKE_LOG;
