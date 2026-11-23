-- V005: views for the hosted matching agents. The agent group sees nothing else.
-- Each view is the fixed query behind one agent tool; the tool only supplies parameters.
-- Port of snowflake/migrations/V005__agent_api.sql. Databricks has no SECURE VIEW; a Unity Catalog view
-- already runs with its owner's rights, so PVSWEEP_AGENT needs SELECT on the views only (V004), never on
-- PV or REF. Unlike a Snowflake secure view, the view text is visible to users who can see the view.
-- Every view is owned by PVSWEEP_ADMIN, which holds ALL PRIVILEGES on the catalog (bootstrap), so the
-- owner's rights do not depend on the engineer who ran the migration.
-- ARRAY_AGG(DISTINCT x) WITHIN GROUP (ORDER BY x) becomes array_sort(collect_set(x)); both skip NULLs.

-- Tool search_safety_cases: one row per case with the suspect products and events aggregated.
CREATE OR REPLACE VIEW ${catalog}.AGENT_API.SAFETY_CASE_SUMMARY AS
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
FROM ${catalog}.PV.SAFETY_CASE c
LEFT JOIN (
  SELECT case_id,
         array_sort(collect_set(substance))    AS substances,
         array_sort(collect_set(product_name)) AS products
  FROM ${catalog}.PV.CASE_DRUG WHERE role IN ('primary_suspect', 'secondary_suspect') GROUP BY case_id
) d ON d.case_id = c.case_id
LEFT JOIN (
  SELECT case_id, array_sort(collect_set(pt)) AS events
  FROM ${catalog}.PV.CASE_EVENT GROUP BY case_id
) e ON e.case_id = c.case_id;

-- Tool get_case_history: versions of a case with what each one added.
CREATE OR REPLACE VIEW ${catalog}.AGENT_API.CASE_HISTORY AS
SELECT case_id, case_version, received_date, significant, information_summary
FROM ${catalog}.PV.CASE_VERSION;

-- Tool search_intake_queue: items received by PV but not yet in the safety database.
CREATE OR REPLACE VIEW ${catalog}.AGENT_API.INTAKE_QUEUE AS
SELECT intake_id, channel_code, vendor_reference, received_by_pv, status, case_id, summary
FROM ${catalog}.PV.INTAKE_QUEUE;

-- Tool search_vendor_log: what vendors say they sent.
CREATE OR REPLACE VIEW ${catalog}.AGENT_API.VENDOR_TX_LOG AS
SELECT vendor_code, vendor_reference, sent_at, product_name, event_summary
FROM ${catalog}.PV.VENDOR_TX_LOG;

-- Reference the agent may need to normalise a brand to a substance.
CREATE OR REPLACE VIEW ${catalog}.AGENT_API.PRODUCT AS
SELECT substance, brand FROM ${catalog}.REF.PRODUCT;

-- Tool search_intake_log: PV's own record of what it received from a vendor.
CREATE OR REPLACE VIEW ${catalog}.AGENT_API.INTAKE_LOG AS
SELECT intake_id, vendor_code, vendor_reference, received_by_pv, product_name, event_summary
FROM ${catalog}.PV.INTAKE_LOG;

ALTER VIEW ${catalog}.AGENT_API.SAFETY_CASE_SUMMARY OWNER TO `${pvsweep_admin}`;
ALTER VIEW ${catalog}.AGENT_API.CASE_HISTORY        OWNER TO `${pvsweep_admin}`;
ALTER VIEW ${catalog}.AGENT_API.INTAKE_QUEUE        OWNER TO `${pvsweep_admin}`;
ALTER VIEW ${catalog}.AGENT_API.VENDOR_TX_LOG       OWNER TO `${pvsweep_admin}`;
ALTER VIEW ${catalog}.AGENT_API.PRODUCT             OWNER TO `${pvsweep_admin}`;
ALTER VIEW ${catalog}.AGENT_API.INTAKE_LOG          OWNER TO `${pvsweep_admin}`;
