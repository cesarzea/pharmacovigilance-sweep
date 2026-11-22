"""Render each scenario into channel-style text with a model, then validate the planted facts.

The model only writes prose. It receives the facts to include and the facts to leave out; the
validator rejects texts that miss a planted fact, mention the wrong product, or contradict the
causality statement, and the renderer retries with the validator's complaint added.
"""

from __future__ import annotations

import json
import re

from . import catalogue as C

SYSTEM = (
    "You write realistic source records for a pharmacovigilance test dataset. You will be given the "
    "style of the record and a list of facts. Write the record in English so that every listed fact is "
    "present (dates may be written in words or as dd/mm/yyyy, ages as numbers, names as given). "
    "Do not add any other medical event, product, dose change, date or outcome. Do not mention "
    "pharmacovigilance, reporting or adverse-event terminology unless the facts say so. Paraphrase the "
    "facts the way the writer of such a record would; never copy the wording of the fact list. Output "
    "only the record text, no title, no quotes."
)


def facts_for(s: dict, brands: dict[str, str]) -> tuple[list[str], list[str]]:
    """Facts the text must contain, and things it must not contain."""
    must, must_not = [], []
    if s["kind"] == "NO_PV_CONTENT":
        must.append(f"The contact is about: {s['topic']}; product: {s['product_name']}")
        must_not.append("any symptom, illness, hospital visit or side effect")
        if s["reporter_name"]:
            must.append(f"The person contacting is {s['reporter_name']} ({s['reporter_type']})")
        return must, must_not

    must.append(f"Product: {s['product_name']}")
    if s["identifiable_patient"]:
        must.append(f"Patient: initials {s['patient_initials']}, {s['patient_age']} years old, {s['patient_sex']}")
    else:
        must_not.append("any patient initials, age or sex")
    if s["identifiable_reporter"] and s["reporter_name"]:
        must.append(f"Reporter: {s['reporter_name']}, {s['reporter_type']}")
    elif s["channel"] == "SOCIAL":
        must.append("Written by the patient themself under a forum nickname, no real name")
    else:
        must_not.append("the reporter's name or contact details (the caller refused to give them)")

    if s["kind"] == "SPECIAL_SITUATION":
        must.append(f"Situation: {s['event_context']} (type: {s['special_situation'].replace('_', ' ')})")
        must_not.append("any symptom or adverse effect")
    elif s["kind"] == "PLANNED_PROCEDURE":
        must.append(f"The patient was admitted to hospital: {s['event_context']}")
        must.append("The admission was planned before the treatment started and nobody links it to the medicine")
    else:
        must.append(f"Event: {s['event_pt'].lower()} - {s['event_context']}")
        if s["onset_date"]:
            must.append(f"The event started around {s['onset_date']}")
        if s["hospitalisation"]:
            must.append("The patient was admitted to hospital because of it")
        if s["causality_statement"] == "suspected":
            must.append("The reporter thinks the medicine caused it")
        elif s["causality_statement"] == "excluded":
            must.append("The reporter explicitly says the medicine did not cause it")
        else:
            must_not.append("any opinion on whether the medicine caused the event")
    if s["kind"] == "SIGNIFICANT_FOLLOW_UP":
        must.append(f"This is an update on an earlier report; new information: {s['extra_facts']['new_information']}")
    if s["kind"] == "NON_SIGNIFICANT_FOLLOW_UP":
        must.append("The contact mentions they already reported this same patient and event before and nothing has changed since")
    if s["kind"] == "OTHER_MAH_PRODUCT":
        must_not.append("any Contoso product: " + ", ".join(brands.values()))
    if s["channel"] in ("MI", "PSP") and s["extra_facts"].get("vendor_reference"):
        must.append(f"Reference number: {s['extra_facts']['vendor_reference']}")
    return must, must_not


def validate(text: str, s: dict, brands: dict[str, str]) -> list[str]:
    """Return the list of problems; empty means the text passes."""
    problems = []
    low = text.lower()

    def present(token: str) -> bool:
        return token.lower() in low

    if s["product_name"] and not present(s["product_name"]):
        problems.append(f"product name '{s['product_name']}' missing")
    if s["kind"] == "OTHER_MAH_PRODUCT":
        for b in brands.values():
            if present(b):
                problems.append(f"Contoso brand '{b}' must not appear")
    if s["kind"] != "NO_PV_CONTENT":
        if s["identifiable_patient"]:
            if not present(s["patient_initials"]) and not re.search(r"\b(patient|woman|man|she|he)\b", low):
                problems.append("patient initials missing")
            if str(s["patient_age"]) not in text:
                problems.append("patient age missing")
        else:
            if re.search(r"\b\d{2}[- ]?(years|year old|yo|y\.o\.)\b", low):
                problems.append("age present but patient must be unidentifiable")
        if s["identifiable_reporter"] and s["reporter_name"]:
            surname_initial = s["reporter_name"].split()[0]
            if not present(surname_initial):
                problems.append(f"reporter name '{s['reporter_name']}' missing")
        if s["kind"] in ("SPECIAL_SITUATION",):
            pass
        elif s["kind"] != "PLANNED_PROCEDURE":
            key = s["event_pt"].lower().split()[0]
            synonyms = {"electrocardiogram": ["ecg", "qt"], "hyponatraemia": ["sodium", "hyponat"],
                        "gastrointestinal": ["black stool", "bleed", "haemorrhage", "hemorrhage"],
                        "syncope": ["faint", "syncope", "collapse"], "suicidal": ["self-harm", "suicid"],
                        "serotonin": ["serotonin", "agitation", "tremor"], "sexual": ["libido", "sexual"],
                        "weight": ["weight", "kilo", "kg"], "hyperhidrosis": ["sweat"], "rash": ["rash"],
                        "arrhythmia": ["arrhythm", "irregular heart", "palpitation"], "seizure": ["seizure", "fit", "convuls"],
                        "nausea": ["nausea", "sick"], "insomnia": ["insomnia", "sleep"], "headache": ["headache"],
                        "dizziness": ["dizz"]}
            if not any(present(t) for t in synonyms.get(key, [key])):
                problems.append(f"event '{s['event_pt']}' not described")
        if s["causality_statement"] == "excluded" and not re.search(r"\b(not|n't|unrelated|nothing to do)\b", low):
            problems.append("explicit exclusion of causality missing")
        if s["hospitalisation"] and not re.search(r"hospital|admitted|admission|a&e|emergency", low):
            problems.append("hospital admission missing")
        if s["kind"] == "SIGNIFICANT_FOLLOW_UP" and not re.search(r"update|earlier|previous|again|follow", low):
            problems.append("follow-up framing missing")
        ref = s["extra_facts"].get("vendor_reference")
        if ref and s["channel"] in ("MI", "PSP") and ref not in text:
            problems.append(f"reference {ref} missing")
    else:
        if re.search(r"hospital|side effect|nausea|headache|dizz|rash|seizure|suicid", low):
            problems.append("NO_PV_CONTENT text mentions a medical event")
    words = len(text.split())
    if words < 25 or words > 220:
        problems.append(f"length {words} words out of range")
    return problems


def user_prompt(s: dict, brands: dict[str, str], complaint: str | None) -> str:
    must, must_not = facts_for(s, brands)
    parts = [f"Style: {C.CHANNEL_STYLE[s['channel']]}.",
             f"Country of the contact: {s['country']}. Date of the record: {s['channel_received_date']}.",
             "Facts that must appear:\n- " + "\n- ".join(must)]
    if must_not:
        parts.append("Must NOT appear:\n- " + "\n- ".join(must_not))
    if complaint:
        parts.append(f"Your previous attempt was rejected: {complaint}. Write it again and fix that.")
    return "\n\n".join(parts)


def to_jsonable(s: dict) -> str:
    return json.dumps(s, ensure_ascii=False)
