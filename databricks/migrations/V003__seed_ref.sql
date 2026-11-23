-- V003: reference seed. Idempotent (MERGE). Brands must match config/brands.json.
-- Port of snowflake/migrations/V003__seed_ref.sql. Databricks names unnamed VALUES columns col1, col2...
-- (Snowflake: column1...), so every VALUES list carries an alias, and every INSERT lists its columns.

MERGE INTO ${catalog}.REF.PRODUCT t USING (
  SELECT * FROM VALUES
    ('sertraline',   'Sertavix', 'N06AB06'),
    ('escitalopram', 'Escitrel', 'N06AB10'),
    ('duloxetine',   'Duloxane', 'N06AX21'),
    ('venlafaxine',  'Venlaris', 'N06AX16')
  AS v(substance, brand, atc_code)
) s ON t.substance = s.substance
WHEN MATCHED THEN UPDATE SET brand = s.brand, atc_code = s.atc_code
WHEN NOT MATCHED THEN INSERT (substance, brand, atc_code) VALUES (s.substance, s.brand, s.atc_code);

MERGE INTO ${catalog}.REF.VENDOR t USING (
  SELECT vendor_code, vendor_name, CAST(forwarding_business_days AS BIGINT) AS forwarding_business_days FROM VALUES
    ('PSPV',  'Northline Patient Services (PSP vendor)', 1),
    ('MIV',   'Calloway Medical Information (MI vendor)', 1),
    ('SOCV',  'Signalbridge Listening (social listening agency)', 2)
  AS v(vendor_code, vendor_name, forwarding_business_days)
) s ON t.vendor_code = s.vendor_code
WHEN MATCHED THEN UPDATE SET vendor_name = s.vendor_name, forwarding_business_days = s.forwarding_business_days
WHEN NOT MATCHED THEN INSERT (vendor_code, vendor_name, forwarding_business_days)
  VALUES (s.vendor_code, s.vendor_name, s.forwarding_business_days);

MERGE INTO ${catalog}.REF.CHANNEL t USING (
  SELECT channel_code, channel_name, report_type, operated_by, CAST(vendor_code AS STRING) AS vendor_code FROM VALUES
    ('MI',     'Medical information enquiries',            'spontaneous', 'vendor', 'MIV'),
    ('CRM',    'Field-force call notes',                   'spontaneous', 'MAH',    NULL),
    ('PSP',    'Patient support programme',                'solicited',   'vendor', 'PSPV'),
    ('PQC',    'Product quality complaints',               'spontaneous', 'MAH',    NULL),
    ('SOCIAL', 'Social listening programme (ODCS)',        'solicited',   'vendor', 'SOCV')
  AS v(channel_code, channel_name, report_type, operated_by, vendor_code)
) s ON t.channel_code = s.channel_code
WHEN MATCHED THEN UPDATE SET channel_name = s.channel_name, report_type = s.report_type,
                             operated_by = s.operated_by, vendor_code = s.vendor_code
WHEN NOT MATCHED THEN INSERT (channel_code, channel_name, report_type, operated_by, vendor_code)
  VALUES (s.channel_code, s.channel_name, s.report_type, s.operated_by, s.vendor_code);

-- Demo IME list: serious-event terms used by the scenarios, plus synonyms extractors propose.
-- Not the EMA list. Keep identical to LocalStore.ime_terms() in runner/pvsweep_runner/store.py.
MERGE INTO ${catalog}.REF.IME_TERM t USING (
  SELECT pt_name, 'demo list' AS source FROM VALUES
    ('Serotonin syndrome'), ('Hyponatraemia'), ('Electrocardiogram QT prolonged'), ('Torsade de pointes'),
    ('Arrhythmia'), ('Suicidal ideation'), ('Suicide attempt'), ('Completed suicide'), ('Seizure'),
    ('Gastrointestinal haemorrhage'), ('Hepatic failure'), ('Neuroleptic malignant syndrome'),
    ('Anaphylactic reaction'), ('Stevens-Johnson syndrome'), ('Agranulocytosis'), ('Rhabdomyolysis'),
    ('Syncope'), ('Self-harm ideation'), ('Self-injurious ideation'), ('Suicidal thoughts'),
    ('QT prolonged'), ('QT prolongation'), ('Loss of consciousness'), ('Fainting')
  AS v(pt_name)
) s ON t.pt_name = s.pt_name AND t.source = s.source
WHEN NOT MATCHED THEN INSERT (pt_name, source) VALUES (s.pt_name, s.source);
