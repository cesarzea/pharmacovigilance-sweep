-- V003: reference seed. Idempotent (MERGE). Brands must match config/brands.json.
USE ROLE PVSWEEP_ADMIN;
USE DATABASE PVSWEEP;

MERGE INTO REF.PRODUCT t USING (
  SELECT * FROM VALUES
    ('sertraline',   'Sertavix', 'N06AB06'),
    ('escitalopram', 'Escitrel', 'N06AB10'),
    ('duloxetine',   'Duloxane', 'N06AX21'),
    ('venlafaxine',  'Venlaris', 'N06AX16')
  AS s(substance, brand, atc_code)
) s ON t.substance = s.substance
WHEN MATCHED THEN UPDATE SET brand = s.brand, atc_code = s.atc_code
WHEN NOT MATCHED THEN INSERT (substance, brand, atc_code) VALUES (s.substance, s.brand, s.atc_code);

MERGE INTO REF.VENDOR t USING (
  SELECT * FROM VALUES
    ('PSPV',  'Northline Patient Services (PSP vendor)', 1),
    ('MIV',   'Calloway Medical Information (MI vendor)', 1),
    ('SOCV',  'Signalbridge Listening (social listening agency)', 2)
  AS s(vendor_code, vendor_name, forwarding_business_days)
) s ON t.vendor_code = s.vendor_code
WHEN MATCHED THEN UPDATE SET vendor_name = s.vendor_name, forwarding_business_days = s.forwarding_business_days
WHEN NOT MATCHED THEN INSERT VALUES (s.vendor_code, s.vendor_name, s.forwarding_business_days);

MERGE INTO REF.CHANNEL t USING (
  SELECT * FROM VALUES
    ('MI',     'Medical information enquiries',            'spontaneous', 'vendor', 'MIV'),
    ('CRM',    'Field-force call notes',                   'spontaneous', 'MAH',    NULL),
    ('PSP',    'Patient support programme',                'solicited',   'vendor', 'PSPV'),
    ('PQC',    'Product quality complaints',               'spontaneous', 'MAH',    NULL),
    ('SOCIAL', 'Social listening programme (ODCS)',        'solicited',   'vendor', 'SOCV')
  AS s(channel_code, channel_name, report_type, operated_by, vendor_code)
) s ON t.channel_code = s.channel_code
WHEN MATCHED THEN UPDATE SET channel_name = s.channel_name, report_type = s.report_type,
                             operated_by = s.operated_by, vendor_code = s.vendor_code
WHEN NOT MATCHED THEN INSERT VALUES (s.channel_code, s.channel_name, s.report_type, s.operated_by, s.vendor_code);

-- Demo IME list: serious-event terms used by the scenarios. Not the EMA list.
MERGE INTO REF.IME_TERM t USING (
  SELECT column1 AS pt_name, 'demo list' AS source FROM VALUES
    ('Serotonin syndrome'), ('Hyponatraemia'), ('Electrocardiogram QT prolonged'), ('Torsade de pointes'),
    ('Arrhythmia'), ('Suicidal ideation'), ('Suicide attempt'), ('Completed suicide'), ('Seizure'),
    ('Gastrointestinal haemorrhage'), ('Hepatic failure'), ('Neuroleptic malignant syndrome'),
    ('Anaphylactic reaction'), ('Stevens-Johnson syndrome'), ('Agranulocytosis'), ('Rhabdomyolysis')
) s ON t.pt_name = s.pt_name AND t.source = s.source
WHEN NOT MATCHED THEN INSERT VALUES (s.pt_name, s.source);
