"""Scenario catalogue for the synthetic non-PV channel records.

Scenario-first: every record starts as structured ground truth (this module plus plan.py); an LLM
only writes the text afterwards, and a validator checks that the planted facts appear in it.

Each scenario kind fixes the expected labels at two points of the pipeline:
- screening class (step 1): ADVERSE_EVENT | SPECIAL_SITUATION | NO_PV_CONTENT
- reviewer outcome (step 6): A_NOT_REPORTABLE | B_ALREADY_RECEIVED | C_INCOMPLETE | D_VALID_ICSR
and the expected match outcome (step 4):
  IN_SAFETY_DB | IN_INTAKE_QUEUE | SIGNIFICANT_FOLLOW_UP | NON_SIGNIFICANT_FOLLOW_UP | DUPLICATE_IN_SWEEP | NO_MATCH
"""

from __future__ import annotations

from dataclasses import dataclass, field

CHANNELS = ("MI", "CRM", "PSP", "PQC", "SOCIAL")

# Share of records per channel (about 450 records in total).
CHANNEL_WEIGHTS = {"MI": 0.24, "CRM": 0.18, "PSP": 0.26, "PQC": 0.14, "SOCIAL": 0.18}


@dataclass(frozen=True)
class Kind:
    code: str
    weight: float
    screening: str
    match: str
    outcome: str
    needs_case: bool = False          # anchored on an existing FAERS-derived case
    needs_queue: bool = False         # anchored on an intake-queue item
    has_event: bool = True
    channels: tuple[str, ...] = CHANNELS
    note: str = ""


KINDS: tuple[Kind, ...] = (
    Kind("IN_SAFETY_DB", 0.10, "ADVERSE_EVENT", "IN_SAFETY_DB", "B_ALREADY_RECEIVED", needs_case=True,
         note="rewrite of a case already in the safety database, same facts"),
    Kind("IN_INTAKE_QUEUE", 0.08, "ADVERSE_EVENT", "IN_INTAKE_QUEUE", "B_ALREADY_RECEIVED", needs_queue=True,
         note="already received by PV, pending processing"),
    Kind("SIGNIFICANT_FOLLOW_UP", 0.07, "ADVERSE_EVENT", "SIGNIFICANT_FOLLOW_UP", "D_VALID_ICSR", needs_case=True,
         note="known case plus new hospitalisation or outcome"),
    Kind("NON_SIGNIFICANT_FOLLOW_UP", 0.05, "ADVERSE_EVENT", "NON_SIGNIFICANT_FOLLOW_UP", "B_ALREADY_RECEIVED",
         needs_case=True, note="known case, same information repeated"),
    Kind("NEW_SPONTANEOUS", 0.12, "ADVERSE_EVENT", "NO_MATCH", "D_VALID_ICSR", channels=("MI", "CRM", "PQC"),
         note="new adverse event with reporter attribution"),
    Kind("NEW_SPONTANEOUS_EXCLUDED", 0.03, "ADVERSE_EVENT", "NO_MATCH", "D_VALID_ICSR", channels=("MI", "CRM"),
         note="reporter explicitly excludes the product; still an ICSR for PV to assess"),
    Kind("NEW_PSP_WITH_CAUSALITY", 0.07, "ADVERSE_EVENT", "NO_MATCH", "D_VALID_ICSR", channels=("PSP",),
         note="PSP note where the patient or nurse relates the event to the product"),
    Kind("NEW_PSP_NO_CAUSALITY", 0.08, "ADVERSE_EVENT", "NO_MATCH", "D_VALID_ICSR", channels=("PSP",),
         note="PSP admission note with no reference to the product; causality assessed by PV"),
    Kind("PLANNED_PROCEDURE", 0.05, "ADVERSE_EVENT", "NO_MATCH", "A_NOT_REPORTABLE", channels=("PSP", "CRM", "MI"),
         note="admission for a procedure planned before treatment; routed to PV, closed as not reportable"),
    Kind("SPECIAL_SITUATION", 0.07, "SPECIAL_SITUATION", "NO_MATCH", "A_NOT_REPORTABLE", has_event=False,
         channels=("MI", "PSP", "PQC"), note="overdose, medication error or pregnancy exposure without an adverse event"),
    Kind("INCOMPLETE", 0.08, "ADVERSE_EVENT", "NO_MATCH", "C_INCOMPLETE", channels=("SOCIAL", "MI", "CRM"),
         note="adverse event without an identifiable patient or reporter"),
    Kind("OTHER_MAH_PRODUCT", 0.05, "ADVERSE_EVENT", "NO_MATCH", "A_NOT_REPORTABLE",
         note="another company's product; recorded, not Contoso's case"),
    Kind("NO_PV_CONTENT", 0.15, "NO_PV_CONTENT", "NO_MATCH", "A_NOT_REPORTABLE", has_event=False,
         note="availability, pricing, logistics, packaging"),
)

# Timing variants for records that reach PV late (NO_MATCH kinds with an ICSR outcome).
TIMING = (
    ("WITHIN_TIMELINE", 0.45),   # forwarded within the vendor's timeline, found by the sweep anyway
    ("FORWARDING_BREACHED", 0.35),  # breached the forwarding timeline, regulatory deadline still met
    ("OVERDUE", 0.20),           # regulatory deadline missed
)

SUBSTANCES = ("sertraline", "escitalopram", "duloxetine", "venlafaxine")

# Events with the context the extractor must capture. (pt, seriousness, hospitalisation, typical context)
EVENTS = (
    ("Hyponatraemia", True, True, "admitted with confusion and low sodium"),
    ("Serotonin syndrome", True, True, "agitation, tremor and fever after a dose increase"),
    ("Electrocardiogram QT prolonged", True, False, "found on a routine ECG"),
    ("Arrhythmia", True, True, "admitted for palpitations and an irregular heartbeat"),
    ("Suicidal ideation", True, False, "reported new thoughts of self-harm two weeks after starting"),
    ("Seizure", True, True, "seizure at home, taken to hospital"),
    ("Gastrointestinal haemorrhage", True, True, "black stools, admitted overnight"),
    ("Syncope", True, False, "fainted at work"),
    ("Nausea", False, False, "persistent nausea since the first week"),
    ("Insomnia", False, False, "cannot sleep since starting the tablets"),
    ("Headache", False, False, "daily headaches"),
    ("Dizziness", False, False, "dizzy when standing up"),
    ("Hyperhidrosis", False, False, "sweating heavily at night"),
    ("Weight increased", False, False, "gained weight over three months"),
    ("Sexual dysfunction", False, False, "loss of libido"),
    ("Rash", False, False, "itchy rash on the arms"),
)

PLANNED_PROCEDURES = (
    "knee replacement scheduled last year",
    "elective cataract surgery",
    "planned hernia repair",
    "scheduled hip replacement",
)

SPECIAL_SITUATIONS = (
    ("overdose", "took a double dose by mistake, no symptoms"),
    ("medication_error", "pharmacy dispensed 20 mg instead of 10 mg, noticed before any effect"),
    ("pregnancy_exposure", "found out she is pregnant while on treatment, feeling well"),
    ("lack_of_efficacy", "says the tablets are not helping after eight weeks"),
)

OTHER_MAH_PRODUCTS = ("fluoxetine", "paroxetine", "mirtazapine", "bupropion", "trazodone")

NO_PV_TOPICS = (
    "asks whether the tablets can be split",
    "asks about availability in 20 mg strength",
    "complains that the blister pack is hard to open",
    "asks for the patient leaflet in another language",
    "asks about storage temperature during travel",
    "asks whether the product is reimbursed",
    "reports a damaged carton on delivery, product intact",
    "asks about the difference between the brand and a generic",
)

REPORTERS = {
    "MI": (("pharmacist", 0.4), ("physician", 0.3), ("consumer", 0.3)),
    "CRM": (("physician", 0.8), ("pharmacist", 0.2)),
    "PSP": (("nurse", 0.6), ("consumer", 0.4)),
    "PQC": (("pharmacist", 0.5), ("consumer", 0.5)),
    "SOCIAL": (("consumer", 1.0),),
}

FIRST_NAMES = ("Anna", "Luca", "Marie", "Jonas", "Sofia", "Pieter", "Elena", "Tomasz", "Ingrid", "Mateo",
               "Clara", "Niels", "Zofia", "Hugo", "Lena", "Rafael", "Maja", "Olivier", "Ines", "Karl")
COUNTRIES = ("DE", "FR", "IT", "ES", "NL", "SE", "PL", "BE", "AT", "PT", "IE", "DK")

CHANNEL_STYLE = {
    "MI": "a medical information call log entry written by the call-centre agent: short, factual, third person, "
          "with caller type and the question asked; 60-140 words",
    "CRM": "a field-force CRM visit note typed by a sales representative after visiting a prescriber: informal, "
           "abbreviations, mixes commercial talk with what the doctor mentioned; 50-120 words",
    "PSP": "a patient support programme nurse call note: structured, clinical but plain, documents adherence "
           "and wellbeing checks and anything the patient reported; 70-150 words",
    "PQC": "a product quality complaint form free-text field filled in by a pharmacist or patient: describes "
           "the product, batch and the complaint; 40-110 words",
    "SOCIAL": "a post on an online patient forum about antidepressants: first person, casual, may name the "
              "brand or the generic, no personal identifiers beyond what is listed; 40-120 words",
}

# Which minimum criteria a record of each channel carries by default (patient, reporter).
# INCOMPLETE records drop one of them; SOCIAL posts never carry an identifiable reporter.
DEFAULT_IDENTIFIABLE = {"MI": (True, True), "CRM": (True, True), "PSP": (True, True), "PQC": (True, True),
                        "SOCIAL": (True, False)}


@dataclass
class Scenario:
    record_id: str
    channel: str
    kind: str
    timing: str | None
    substance: str | None
    product_name: str | None
    ownership: str
    reporter_type: str
    reporter_name: str | None
    patient_initials: str | None
    patient_age: int | None
    patient_sex: str | None
    country: str
    event_pt: str | None
    event_context: str | None
    serious: bool
    hospitalisation: bool
    causality_statement: str      # suspected | excluded | not_stated
    special_situation: str | None
    onset_date: str | None
    channel_received_date: str
    vendor_sent_date: str | None
    pv_received_date: str | None
    anchor_case_id: str | None
    anchor_intake_id: str | None
    identifiable_patient: bool
    identifiable_reporter: bool
    topic: str | None = None
    extra_facts: dict = field(default_factory=dict)
    # gold labels
    gold_screening: str = ""
    gold_match: str = ""
    gold_outcome: str = ""
    gold_day0: str | None = None
