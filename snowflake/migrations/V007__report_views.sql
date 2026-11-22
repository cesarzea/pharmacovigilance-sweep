-- V007: report views. Transmission reconciliation is pure SQL (no model); the KPI views read the
-- sweep results and reviewer decisions. Written in portable SQL so the same queries run on the local
-- DuckDB backend (runner/pvsweep_runner/report.py).
USE ROLE PVSWEEP_ADMIN;
USE DATABASE PVSWEEP;

-- Vendor transmission log vs PV intake log, by vendor reference.
CREATE OR REPLACE VIEW REPORT.RECONCILIATION AS
SELECT COALESCE(v.vendor_code, i.vendor_code)            AS vendor_code,
       COALESCE(v.vendor_reference, i.vendor_reference)  AS vendor_reference,
       v.sent_at,
       i.received_by_pv,
       CASE WHEN v.vendor_reference IS NOT NULL AND i.vendor_reference IS NOT NULL THEN 'received_as_sent'
            WHEN v.vendor_reference IS NOT NULL THEN 'sent_never_received'
            ELSE 'received_not_in_vendor_log' END        AS status,
       v.product_name, v.event_summary
FROM PV.VENDOR_TX_LOG v
FULL OUTER JOIN PV.INTAKE_LOG i
  ON i.vendor_code = v.vendor_code AND i.vendor_reference = v.vendor_reference;

CREATE OR REPLACE VIEW REPORT.RECONCILIATION_SUMMARY AS
SELECT vendor_code,
       COUNT(*)                                                  AS items,
       SUM(CASE WHEN status = 'received_as_sent' THEN 1 ELSE 0 END)           AS received_as_sent,
       SUM(CASE WHEN status = 'sent_never_received' THEN 1 ELSE 0 END)        AS sent_never_received,
       SUM(CASE WHEN status = 'received_not_in_vendor_log' THEN 1 ELSE 0 END) AS received_not_in_vendor_log
FROM REPORT.RECONCILIATION
GROUP BY vendor_code;

-- Per run and channel: what the sweep surfaced and where it stands.
CREATE OR REPLACE VIEW REPORT.CHANNEL_KPI AS
SELECT s.run_id,
       src.channel_code,
       COUNT(*)                                                                    AS records_screened,
       SUM(CASE WHEN s.screening_class IN ('ADVERSE_EVENT','SPECIAL_SITUATION') THEN 1 ELSE 0 END) AS routed_to_pv,
       SUM(CASE WHEN m.outcome = 'NO_MATCH' THEN 1 ELSE 0 END)                    AS potential_new_cases,
       SUM(CASE WHEN m.outcome IN ('IN_SAFETY_DB','IN_INTAKE_QUEUE','NON_SIGNIFICANT_FOLLOW_UP') THEN 1 ELSE 0 END) AS already_received,
       SUM(CASE WHEN m.outcome = 'SIGNIFICANT_FOLLOW_UP' THEN 1 ELSE 0 END)       AS significant_follow_ups,
       SUM(CASE WHEN r.regulatory_status = 'overdue' THEN 1 ELSE 0 END)           AS overdue_at_detection,
       SUM(CASE WHEN r.regulatory_status = 'at_risk' THEN 1 ELSE 0 END)           AS at_risk_at_detection,
       SUM(CASE WHEN r.forwarding_status = 'breached' THEN 1 ELSE 0 END)          AS forwarding_breaches,
       SUM(CASE WHEN s.screening_class IN ('BLOCKED','INVALID') THEN 1 ELSE 0 END) AS needs_human_qc
FROM SWEEP.SCREENING s
JOIN SRC.SOURCE_RECORD src ON src.record_id = s.record_id
LEFT JOIN SWEEP.RULE_RESULT r   ON r.run_id = s.run_id AND r.record_id = s.record_id
LEFT JOIN SWEEP.MATCH_DECISION m ON m.run_id = s.run_id AND m.record_id = s.record_id
GROUP BY s.run_id, src.channel_code;

-- Model comparison from the audit trail: cost, latency and failures per run, step and deployment.
CREATE OR REPLACE VIEW REPORT.MODEL_COMPARISON AS
SELECT c.run_id, r.provider, c.step, c.deployment,
       COUNT(*)                                  AS calls,
       SUM(c.input_tokens)                       AS input_tokens,
       SUM(c.cached_tokens)                      AS cached_tokens,
       SUM(c.output_tokens)                      AS output_tokens,
       AVG(c.latency_ms)                         AS latency_ms_avg,
       SUM(CASE WHEN c.status <> 'ok' THEN 1 ELSE 0 END) AS failed_calls
FROM AUDIT.MODEL_CALL c
JOIN SWEEP.RUN r ON r.run_id = c.run_id
GROUP BY c.run_id, r.provider, c.step, c.deployment;

GRANT SELECT ON ALL VIEWS IN SCHEMA REPORT TO ROLE PVSWEEP_REVIEW_APP;
GRANT SELECT ON ALL VIEWS IN SCHEMA REPORT TO ROLE PVSWEEP_ANALYST;
