"""Render every frame of the full walkthrough (docs/demo/script-full.md) into docs/demo/full/frames/NN.png:
slides and box-and-arrow diagrams drawn with Pillow in the site's style, screenshots composed on the
same layout, and the four slides shared with the short demo.

    uv run --no-project --with pillow python -I scripts/demo_full_frames.py [--only 9,15]

Then: scripts/make_demo_video.py --script docs/demo/script-full.md --frames-dir docs/demo/full/frames
--name full --no-shots, and scripts/make_demo_audio.py with the same --script/--frames-dir/--name.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_demo_frames import (  # noqa: E402
    CARD, GOLD, GREEN, INK, MONO, MUTED, SANS, SERIF, W, H, canvas, footer, frame_00, frame_01, frame_02, frame_10, label,
    load, wrap,
)
from make_demo_video import place_shot  # noqa: E402

OUT = Path("docs/demo/full/frames")
SHOTS = Path("docs/demo/frames/shots")
SCRIPT = Path("docs/demo/script-full.md")
LINE = (44, 44, 52)
TOTAL = 43


def captions() -> dict[int, str]:
    out = {}
    for line in SCRIPT.read_text().splitlines():
        m = re.match(r"\|\s*(\d+)\s*\|([^|]*)\|([^|]*)\|", line)
        if m:
            out[int(m.group(1))] = m.group(3).strip()
    return out


CAPS = captions()


# ---------------------------------------------------------------- building blocks

def headline(d: ImageDraw.ImageDraw, section: str, line1: str, line2: str = "", y: int = 120) -> int:
    """Section label, a serif line and an italic gold line; returns the y below them."""
    label(d, (96, y), section)
    d.text((96, y + 60), line1, font=load(SERIF, 80, "Light"), fill=INK)
    if line2:
        d.text((96, y + 160), line2, font=load(SERIF, 80, "Light Italic"), fill=GOLD)
        return y + 290
    return y + 180


def bullets(d: ImageDraw.ImageDraw, items: list[str], x: int, y: int, width: int, size: int = 32, gap: int = 14,
            color=INK) -> int:
    font = load(SANS, size)
    for it in items:
        d.ellipse([x, y + size // 2 - 4, x + 8, y + size // 2 + 4], fill=GOLD)
        yy = y
        for ln in wrap(d, it, font, width - 32):
            d.text((x + 28, yy), ln, font=font, fill=color)
            yy += int(size * 1.35)
        y = yy + gap
    return y


def card(d: ImageDraw.ImageDraw, box: tuple[int, int, int, int], title: str, lines: list[str], tag: str = "",
         title_size: int = 32, body_size: int = 26, accent=GOLD) -> None:
    x0, y0, x1, y1 = box
    d.rounded_rectangle(box, radius=14, fill=CARD, outline=LINE, width=1)
    if tag:
        d.text((x0 + 24, y0 + 20), tag, font=load(MONO, 20), fill=accent)
    ty = y0 + (56 if tag else 24)
    d.text((x0 + 24, ty), title, font=load(SANS, title_size), fill=INK)
    yy = ty + int(title_size * 1.5)
    body = load(SANS, body_size)
    for ln in lines:
        for w in wrap(d, ln, body, x1 - x0 - 48):
            d.text((x0 + 24, yy), w, font=body, fill=MUTED)
            yy += int(body_size * 1.35)
        yy += 6


def node(d: ImageDraw.ImageDraw, box: tuple[int, int, int, int], title: str, sub: str = "", accent=GOLD, fill=CARD) -> None:
    x0, y0, x1, y1 = box
    d.rounded_rectangle(box, radius=12, fill=fill, outline=LINE, width=1)
    d.rectangle([x0, y0 + 10, x0 + 4, y1 - 10], fill=accent)
    cx = (x0 + x1) // 2
    if sub:
        d.text((cx, (y0 + y1) // 2 - 16), title, font=load(SANS, 28), fill=INK, anchor="mm")
        d.text((cx, (y0 + y1) // 2 + 20), sub, font=load(SANS, 22), fill=MUTED, anchor="mm")
    else:
        d.text((cx, (y0 + y1) // 2), title, font=load(SANS, 28), fill=INK, anchor="mm")


def arrow(d: ImageDraw.ImageDraw, a: tuple[int, int], b: tuple[int, int], text: str = "", color=(120, 120, 130)) -> None:
    d.line([a, b], fill=color, width=3)
    import math
    ang = math.atan2(b[1] - a[1], b[0] - a[0])
    for s in (-0.5, 0.5):
        d.line([b, (b[0] - 18 * math.cos(ang + s), b[1] - 18 * math.sin(ang + s))], fill=color, width=3)
    if text:
        mx, my = (a[0] + b[0]) // 2, (a[1] + b[1]) // 2
        f = load(MONO, 18)
        tw = d.textlength(text, font=f)
        d.rectangle([mx - tw / 2 - 8, my - 14, mx + tw / 2 + 8, my + 14], fill=(11, 11, 14))
        d.text((mx, my), text, font=f, fill=GOLD, anchor="mm")


def group(d: ImageDraw.ImageDraw, box: tuple[int, int, int, int], title: str) -> None:
    d.rounded_rectangle(box, radius=16, outline=(70, 70, 80), width=2)
    d.text((box[0] + 20, box[1] + 12), title.upper(), font=load(MONO, 20), fill=GOLD)


KARAOKE = True   # captions are burned in as timed subtitles by make_demo_audio.py, so frames carry no caption text


def finish(im: Image.Image, d: ImageDraw.ImageDraw, n: int) -> Image.Image:
    footer(im, d, "" if KARAOKE else CAPS.get(n, ""), None, n, TOTAL)
    return im


# ---------------------------------------------------------------- frames

def f02(n: int) -> Image.Image:
    im, d = canvas()
    y = headline(d, "The regulatory clock", "Day 0 is the first time anyone", "in the company hears of the case.")
    # timeline
    x0, x1, ty = 260, 1700, y + 80
    d.line([(x0, ty), (x1, ty)], fill=LINE, width=4)
    for x, t, s, c in [(x0, "Day 0", "minimum criteria known by anyone, vendor included", GOLD),
                       (x0 + 420, "Forwarding", "vendor to PV within the SDEA timeline (e.g. 1 business day)", GREEN),
                       (x0 + 900, "Day 15", "serious cases: expedited report due", (224, 122, 95)),
                       (x1, "Day 90", "non-serious cases", MUTED)]:
        d.ellipse([x - 12, ty - 12, x + 12, ty + 12], fill=c)
        d.text((x, ty - 40), t, font=load(SANS, 30), fill=INK, anchor="mm")
        for i, ln in enumerate(wrap(d, s, load(SANS, 24), 300)):
            d.text((x, ty + 44 + i * 30), ln, font=load(SANS, 24), fill=MUTED, anchor="mm")
    bullets(d, ["A significant follow-up restarts the clock at its own receipt date; the case keeps its initial receipt date (GVP VI.B.7).",
                "A report that waits in a channel is late, or missing, when the inspector asks: the clock ran anyway."],
            96, ty + 150, 1700, 30)
    return finish(im, d, n)


def f03(n: int) -> Image.Image:
    im, d = canvas()
    y = headline(d, "Two distinct jobs", "Did PV receive everything?", "Is there anything nobody passed on?")
    card(d, (96, y, 940, y + 420), "Transmission reconciliation",
         ["Inputs: vendor transmission log, PV intake log", "Method: deterministic matching on references, dates and counts",
          "Finding: \"vendor sent 120 reports this month; PV logged 118\"", "AI needed: no"], tag="JOB 1")
    card(d, (980, y, 1824, y + 420), "Source re-screening",
         ["Inputs: free-text source records", "Method: LLM screening and extraction, agent-assisted matching, human assessment",
          "Finding: \"this PSP note records an admission for arrhythmia; nobody assessed the product\"", "AI needed: yes"], tag="JOB 2")
    return finish(im, d, n)


def f04(n: int) -> Image.Image:
    im, d = canvas()
    y = headline(d, "Report types · ICH E2D(R1)", "Spontaneous or solicited", "changes what reportable means.")
    card(d, (96, y, 940, y + 300), "Spontaneous", ["Unsolicited: medical information calls, field notes, quality complaints, a post found by chance",
                                                   "Reporting implies a suspected causal relationship"], tag="MI · CRM · PQC")
    card(d, (980, y, 1824, y + 300), "Solicited (organised data collection)",
         ["Patient support programmes, planned social listening, market research", "Needs a causality assessment; reportable only if a relationship is at least possible",
          "Day 0 for social listening: when the reviewer identifies the minimum criteria"], tag="PSP · SOCIAL")
    bullets(d, ["The sweep carries the report type from the channel into the rules, the agent payload and the finding."], 96, y + 340, 1700, 30)
    return finish(im, d, n)


def f06(n: int) -> Image.Image:
    im, d = canvas()
    y = headline(d, "Step 1 · Screen", "One call, one strict schema.", "Nothing for PV stops here.")
    card(d, (96, y, 800, y + 330), "Output", ["screening_class: ADVERSE_EVENT | SPECIAL_SITUATION | NO_PV_CONTENT",
                                              "the four minimum criteria: patient, reporter, product, event", "evidence: verbatim quotes", "confidence"], tag="SMALL MODEL · JSON SCHEMA")
    card(d, (840, y, 1824, y + 330), "Example", ["\"Visited Dr today re Duloxane follow-up. Mentioned pt SG, 52 yo female, black stools… admitted to hospital overnight because of the GI bleed.\"",
                                                  "· ADVERSE_EVENT · patient, reporter, product and event: all four present"], tag="CRM NOTE")
    bullets(d, ["Invalid JSON is retried once; a second failure is counted and not routed silently.",
                "A ranked 5 % sample of screened-out records goes to a person: nothing is closed unseen."], 96, y + 370, 1700, 30)
    return finish(im, d, n)


def f07(n: int) -> Image.Image:
    im, d = canvas()
    y = headline(d, "Step 2 · Extract", "Case facts,", "every one with its quote.")
    fields = [("Patient", "sex, age, initials"), ("Reporter", "type, identifiable"), ("Products", "names, suspect, batch"),
              ("Events", "verbatim, proposed term, hospitalisation"), ("Seriousness", "criteria, death, life-threatening…"),
              ("Dates", "onset, channel receipt"), ("Causality", "statement, assessment required"), ("Context", "planned procedure, follow-up")]
    x, yy, cw, ch = 96, y, 410, 120
    for i, (t, s) in enumerate(fields):
        bx = x + (i % 4) * (cw + 20)
        by = yy + (i // 4) * (ch + 20)
        card(d, (bx, by, bx + cw, by + ch), t, [s], title_size=28, body_size=22)
    bullets(d, ["Validated against the JSON schema and against the text: a quote that is not in the record is a validation error.",
                "If the small model fails validation, the record is escalated once to the large model (61 of 370 records in round 3)."],
            96, yy + 2 * (ch + 20) + 20, 1700, 30)
    return finish(im, d, n)


def f08(n: int) -> Image.Image:
    im, d = canvas()
    y = headline(d, "Step 3 · Rules", "Deterministic.", "No model decides a deadline.")
    rules = [("Ownership", "own brand, own substance, other MAH", GOLD), ("Seriousness", "criteria + the IME list (bring your own)", GOLD),
             ("Day 0 and deadline", "15 or 90 days from day 0; days remaining", (224, 122, 95)),
             ("Regulatory status", "on time · at risk · overdue · clock not started", (224, 122, 95)),
             ("Forwarding", "channel receipt · PV receipt vs the SDEA timeline", GREEN), ("Report type", "spontaneous or solicited, causality required", GREEN)]
    for i, (t, s, c) in enumerate(rules):
        bx = 96 + (i % 3) * 580
        by = y + (i // 3) * 170
        d.rounded_rectangle([bx, by, bx + 560, by + 150], radius=14, fill=CARD, outline=LINE)
        d.rectangle([bx, by + 12, bx + 5, by + 138], fill=c)
        d.text((bx + 28, by + 24), t, font=load(SANS, 30), fill=INK)
        for j, ln in enumerate(wrap(d, s, load(SANS, 24), 500)):
            d.text((bx + 28, by + 72 + j * 30), ln, font=load(SANS, 24), fill=MUTED)
    bullets(d, ["After matching, a record PV already holds gets no new clock; the overdue count in the KPIs stops counting it."],
            96, y + 360, 1700, 30)
    return finish(im, d, n)


def f09(n: int) -> Image.Image:
    im, d = canvas()
    y = headline(d, "Step 4 · Match", "Has pharmacovigilance", "already got this case?")
    top = y + 20
    node(d, (96, top, 480, top + 110), "Blocking in SQL", "substance · sex · age · dates · initials")
    node(d, (560, top, 940, top + 110), "Candidates", "safety database · queue · vendor log")
    node(d, (1020, top, 1400, top + 110), "Agent", "reads, searches, decides")
    node(d, (1480, top, 1824, top + 110), "submit_match_decision", "strict tool call")
    arrow(d, (480, top + 55), (560, top + 55))
    arrow(d, (940, top + 55), (1020, top + 55))
    arrow(d, (1400, top + 55), (1480, top + 55))
    group(d, (1020, top + 150, 1824, top + 420), "read-only tools · AGENT_API views")
    tools = ["search_safety_cases(substance, initials, …)", "get_case_history(case_id)", "search_intake_queue(text | intake_id)",
             "search_intake_log(…)", "search_vendor_log(…)"]
    for i, t in enumerate(tools):
        d.text((1050, top + 200 + i * 40), t, font=load(MONO, 24), fill=INK)
    group(d, (96, top + 150, 960, top + 420), "outcomes")
    outs = ["NO_MATCH · new case", "IN_SAFETY_DB · link", "IN_INTAKE_QUEUE · already pending", "SIGNIFICANT_FOLLOW_UP · clock restarts",
            "NON_SIGNIFICANT_FOLLOW_UP · no new clock", "BLOCKED · a person looks"]
    for i, t in enumerate(outs):
        d.text((126, top + 200 + i * 36), t, font=load(SANS, 24), fill=INK)
    return finish(im, d, n)


def f10(n: int) -> Image.Image:
    im, d = canvas()
    y = headline(d, "A lesson from the evaluation", "Without an identifier,", "a safety database is full of lookalikes.")
    rows = [("", "Round 2 (no initials)", "Round 3 (initials + prompt v3)"), ("GPT matching", "0.694", "0.835"), ("Claude matching", "0.844", "0.956"),
            ("Lookalikes accepted (GPT)", "37", "3"), ("Known cases missed (Claude)", "18", "6")]
    for i, (a, b, c) in enumerate(rows):
        yy = y + i * 58
        f = load(MONO, 24) if i == 0 else load(SANS, 32)
        col = GOLD if i == 0 else INK
        d.text((96, yy), a, font=f, fill=col)
        d.text((760, yy), b, font=f, fill=col)
        d.text((1240, yy), c, font=f, fill=col)
        if i == 0:
            d.line([(96, yy + 44), (1824, yy + 44)], fill=LINE)
    bullets(d, ["Real safety databases hold patient initials; FAERS does not, so the extract carries deterministic synthetic ones.",
                "The prompt makes initials the primary identity rule; queue candidates are offered only when the event or the initials agree."],
            96, y + 330, 1700, 30)
    return finish(im, d, n)


def f11(n: int) -> Image.Image:
    im, d = canvas()
    y = headline(d, "Step 5 · Finding", "A priority,", "and a proposed intake package.")
    card(d, (96, y, 900, y + 430), "Priority score",
         ["serious +1000 · IME +200 · hospitalisation +100", "overdue +300 · at risk +150 · reviewer sets day 0 +75",
          "forwarding breached +50 · causality required +25", "up to +60 as days remaining fall below 60 · BLOCKED halves the score"], tag="RANKING")
    card(d, (940, y, 1824, y + 430), "Case intake package (JSON, versioned)",
         ["record and channel · product and substance · patient · reporter", "events with terms · seriousness · causality · minimum criteria",
          "dates: channel receipt, proposed day 0, deadline, days remaining, status", "forwarding · match outcome and matched ids · evidence quotes · compliance note"],
         tag="PROPOSAL FOR THE REVIEWER")
    return finish(im, d, n)


def f12(n: int) -> Image.Image:
    im, d = canvas()
    y = headline(d, "Step 6 · Reconcile", "What vendors sent", "against what PV received.")
    node(d, (96, y + 20, 600, y + 130), "Vendor transmission log", "reference · sent_at · product · event")
    node(d, (1320, y + 20, 1824, y + 130), "PV intake log", "reference · received_by_pv")
    node(d, (720, y + 20, 1200, y + 130), "Deterministic match", "reference and date", accent=GREEN)
    arrow(d, (600, y + 75), (720, y + 75))
    arrow(d, (1320, y + 75), (1200, y + 75))
    rows = [("received_as_sent", "both logs agree", GREEN), ("sent_never_received", "the vendor says sent; PV has nothing", (224, 122, 95)),
            ("received_not_in_vendor_log", "PV has it; the vendor never logged it", GOLD)]
    for i, (t, s, c) in enumerate(rows):
        yy = y + 190 + i * 70
        d.ellipse([110, yy + 10, 130, yy + 30], fill=c)
        d.text((150, yy), t, font=load(MONO, 26), fill=INK)
        d.text((700, yy + 2), s, font=load(SANS, 28), fill=MUTED)
    bullets(d, ["Synthetic data plants 20 PSP, 27 MI-vendor and 3 social-listening items as never received: the report view finds all 50.",
                "The channel KPI view adds records screened, routed, potential new cases, overdue and forwarding breaches per run."],
            96, y + 430, 1700, 30)
    return finish(im, d, n)


def f15(n: int) -> Image.Image:
    im, d = canvas()
    y = headline(d, "Architecture · context", "Three systems,", "one repository.")
    top = y
    group(d, (96, top, 620, top + 440), "GitHub")
    node(d, (130, top + 60, 586, top + 150), "Repository", "code, Bicep, SQL, prompts, docs")
    node(d, (130, top + 190, 586, top + 280), "Actions", "CI on push · manual deploy with OIDC")
    group(d, (680, top, 1340, top + 440), "Azure · Microsoft Foundry")
    node(d, (714, top + 60, 1306, top + 140), "GPT and Claude deployments", "Entra ID only")
    node(d, (714, top + 170, 1306, top + 250), "Hosted matching agents", "Foundry Agent Service")
    node(d, (714, top + 280, 1306, top + 360), "Sweep runner", "Container Apps job · Key Vault")
    group(d, (1400, top, 1824, top + 440), "Data platform")
    node(d, (1434, top + 60, 1790, top + 150), "Snowflake", "or Azure Databricks")
    node(d, (1434, top + 190, 1790, top + 280), "Review app", "Streamlit in the platform")
    node(d, (1434, top + 320, 1790, top + 400), "Audit and results", "every call, every decision")
    arrow(d, (620, top + 100), (680, top + 100), "deploy")
    arrow(d, (1340, top + 320), (1400, top + 320), "read / write")
    arrow(d, (1340, top + 210), (1400, top + 210), "views only")
    d.text((96, top + 462), "Reviewers and the operations manager use the review app; the engineer uses the repository; public datasets are pulled at deploy time.",
           font=load(SANS, 24), fill=MUTED)
    return finish(im, d, n)


def f16(n: int) -> Image.Image:
    im, d = canvas()
    y = headline(d, "Architecture · data model", "Ten schemas,", "versioned migrations.")
    schemas = [("REF", "products, channels, vendors, vocabulary, IME terms", GOLD), ("SRC", "source records from the five channels", GOLD),
               ("PV", "safety database extract, intake queue and log, vendor log", GOLD), ("AGENT_API", "secure views: all the agent can see", GREEN),
               ("SWEEP", "runs, screening, extraction, rules, candidates, decisions, findings", (224, 122, 95)),
               ("AUDIT", "one row per model call and agent invocation", (224, 122, 95)), ("REVIEW", "decisions, confirmed packages, compliance findings", (155, 176, 196)),
               ("EVAL", "gold labels, metrics per run, comparisons", (155, 176, 196)),
               ("REPORT", "reconciliation, channel KPIs, model comparison", (155, 176, 196)), ("OPS", "migration history, load stage", MUTED)]
    for i, (t, s, c) in enumerate(schemas):
        bx = 96 + (i % 5) * 350
        by = y + (i // 5) * 190
        d.rounded_rectangle([bx, by, bx + 330, by + 170], radius=14, fill=CARD, outline=LINE)
        d.rectangle([bx, by + 12, bx + 5, by + 158], fill=c)
        d.text((bx + 24, by + 20), t, font=load(MONO, 26), fill=c)
        for j, ln in enumerate(wrap(d, s, load(SANS, 23), 290)):
            d.text((bx + 24, by + 62 + j * 29), ln, font=load(SANS, 23), fill=MUTED)
    return finish(im, d, n)


def f20(n: int) -> Image.Image:
    im, d = canvas()
    y = headline(d, "The hosted agent", "Protocol in, decision out.", "Secrets never sit in the image.")
    top = y + 10
    node(d, (96, top, 420, top + 100), "Runner", "one payload per record")
    node(d, (520, top, 900, top + 100), "Invocations endpoint", "Entra token · session reuse")
    group(d, (980, top - 30, 1824, top + 330), "Foundry sandbox · one container image")
    node(d, (1010, top + 20, 1400, top + 100), "Entry point", "implements SupportsAgentRun")
    node(d, (1430, top + 20, 1794, top + 100), "Matcher", "Agent Framework, GPT or Claude")
    node(d, (1010, top + 140, 1400, top + 220), "Read-only tools", "AGENT_API views")
    node(d, (1430, top + 140, 1794, top + 220), "Models", "called with the agent identity")
    node(d, (1010, top + 250, 1794, top + 310), "Key from a project connection, injected at start", "")
    arrow(d, (420, top + 50), (520, top + 50))
    arrow(d, (900, top + 50), (1010, top + 60))
    bullets(d, ["A wrapper agent with a \"match\" tool would make a model echo a 10,000-token payload into a tool call: slow, costly, and Claude truncated it. The entry point hands the payload to the matcher directly.",
                "Sessions are reused through the agent_session_id query parameter: about 6 s cold, 1 s warm. Error replies become BLOCKED decisions, never silent NO_MATCH."],
            96, top + 140, 850, 24)
    return finish(im, d, n)


def f21(n: int) -> Image.Image:
    im, d = canvas()
    y = headline(d, "The sweep runner", "One package,", "three backends, every call audited.")
    node(d, (96, y, 520, y + 100), "pvsweep_runner", "screen · extract · rules · match · findings")
    node(d, (96, y + 140, 300, y + 220), "DuckDB", "laptop", accent=MUTED)
    node(d, (316, y + 140, 520, y + 220), "Snowflake", "", accent=GOLD)
    node(d, (96, y + 240, 520, y + 320), "Databricks", "", accent=GREEN)
    group(d, (600, y - 30, 1824, y + 360), "Azure · unattended")
    node(d, (630, y + 20, 960, y + 100), "Container Apps job", "0.5 vCPU · manual trigger")
    node(d, (990, y + 20, 1450, y + 100), "User-assigned identity", "Cognitive Services User · Azure AI User")
    node(d, (1480, y + 20, 1794, y + 100), "Key Vault", "Snowflake keys as secret refs")
    node(d, (630, y + 140, 1794, y + 220), "AUDIT.MODEL_CALL · RULE_RESULT · MATCH_DECISION · FINDING",
         "provider, deployment, tokens, cached, latency, status, cost: one row per call")
    node(d, (630, y + 250, 1794, y + 330), "Resilient by design",
         "retries with back-off on 429 · failures become BLOCKED · --resume continues a run · concurrency per quota")
    bullets(d, ["make run-sweep-job starts an execution with its arguments and prints its logs; without --limit it refuses to sweep the whole corpus by accident."],
            96, y + 400, 1700, 28)
    return finish(im, d, n)


def f22(n: int) -> Image.Image:
    im, d = canvas()
    y = headline(d, "Security", "Source text is untrusted.", "The agent can only read.")
    items = [("Read-only, parameterised tools", "the model never writes SQL; every tool is a fixed query over secure views"),
             ("Validation twice", "every output against its JSON schema, and against the payload (ids must exist, quotes must be in the text)"),
             ("No API keys", "Entra ID for models and agents; key-pair service users for the data platform; keys in Key Vault and a project connection"),
             ("Least privilege", "runner: results only · agent: six views · review app: review tables · reviewers: no model access"),
             ("Content filters tested", "overdose and self-harm texts reached assessment unblocked with the default filter"),
             ("Residency", "GPT in the EU data zone; Claude Global Standard (US data zone only), a documented decision for the sponsor")]
    for i, (t, s) in enumerate(items):
        bx = 96 + (i % 2) * 880
        by = y + (i // 2) * 150
        card(d, (bx, by, bx + 850, by + 130), t, [s], title_size=28, body_size=22)
    return finish(im, d, n)


def f25(n: int) -> Image.Image:
    im, d = canvas()
    y = headline(d, "Deploy from the repository · Azure", "make deploy.", "One Bicep deployment, everything.")
    mods = [("main.bicep", "resource group · 50 EUR budget with 80 % / 100 % alerts · parameters file"),
            ("foundry.bicep", "Foundry resource (no local auth) · project · GPT and Claude deployments with capacity and marketplace attestation"),
            ("platform.bicep", "container registry · runner identity · AcrPull · model roles"),
            ("runner.bicep", "Log Analytics · App Insights · Key Vault (RBAC) · Container Apps environment and job"),
            ("connections.bicep", "project connection with the agent's Snowflake key, resolved at agent start"),
            ("databricks.bicep", "the Databricks workspace (optional, DEPLOY_DATABRICKS=1)")]
    for i, (t, s) in enumerate(mods):
        bx = 96 + (i % 2) * 880
        by = y + (i // 2) * 140
        card(d, (bx, by, bx + 850, by + 122), t, [s], title_size=26, body_size=22)
    bullets(d, ["make outputs writes the deployment's outputs to a git-ignored .env file for the other targets; make teardown removes the resource group."],
            96, y + 430, 1700, 28)
    return finish(im, d, n)


def f26(n: int) -> Image.Image:
    im, d = canvas()
    y = headline(d, "Deploy from the repository · data platform", "Keys, bootstrap, migrations,", "load, app. Same on Databricks.")
    steps = [("make snow-keys", "two RSA key pairs into .secrets/ (git-ignored)"), ("make snow-bootstrap", "roles, warehouse, database, service users; once, as ACCOUNTADMIN"),
             ("make snow-migrate", "V001…V009 applied once each, recorded in OPS.MIGRATION"), ("make snow-load", "FAERS and VAERS at pinned revisions, EU subset, date shift, brands remapped; synthetic records"),
             ("make snow-app", "Streamlit review app in Snowflake"), ("make dbx-*", "setup, bootstrap, migrate, load, sync, app, principals, stop")]
    for i, (t, s) in enumerate(steps):
        bx = 96 + (i % 2) * 880
        by = y + (i // 2) * 140
        card(d, (bx, by, bx + 850, by + 122), t, [s], title_size=26, body_size=22)
    bullets(d, ["Lessons are written down: one grantee per GRANT, Parquet logical types, Streamlit ownership, Unity Catalog entitlements and warehouse permissions."],
            96, y + 430, 1700, 28)
    return finish(im, d, n)


def f27(n: int) -> Image.Image:
    im, d = canvas()
    y = headline(d, "Deploy from the repository · agents and jobs", "Build, deploy, run.", "Secrets by file, never by argument.")
    steps = [("make build-agent", "linux/amd64 image built in the registry from agent/Dockerfile"),
             ("make deploy-agents [PLATFORM=databricks]", "one version per provider; grants Azure AI User to each agent identity"),
             ("make kv-secrets", "runner and agent keys into Key Vault with --file, retrying while roles propagate"),
             ("make run-sweep-job SWEEP_ARGS=\"--limit 6\"", "starts the job through the ARM API with an args override, waits, prints the logs"),
             ("make spike-models · make spike-agent", "Entra-only model calls and a hosted-agent probe, kept as a go/no-go check"),
             ("make teardown", "everything in Azure gone; the data platform keeps its own scripts")]
    for i, (t, s) in enumerate(steps):
        bx = 96 + (i % 2) * 880
        by = y + (i // 2) * 140
        card(d, (bx, by, bx + 850, by + 122), t, [s], title_size=26, body_size=22)
    return finish(im, d, n)


def f28(n: int) -> Image.Image:
    im, d = canvas()
    y = headline(d, "GitHub", "CI on every push.", "Deployment by hand, with OIDC.")
    card(d, (96, y, 940, y + 300), "ci.yml", ["uv sync · pytest (69 tests: rules, findings, local schema, Databricks store) · ruff", "runs on push and pull request, no cloud access"], tag="EVERY PUSH")
    card(d, (980, y, 1824, y + 300), "deploy.yml", ["workflow_dispatch · azure/login with OpenID Connect · protected environment", "the parameters file is the only secret · make deploy, build-agent, deploy-agents"], tag="MANUAL")
    bullets(d, ["No AI attribution, no credentials and no account identifiers in the repository or its history: reviewed before publication.",
                "Commit history tells the story: definition, spike, rounds 1 to 3, findings, job, Databricks, demo."], 96, y + 340, 1700, 30)
    return finish(im, d, n)


def f29(n: int) -> Image.Image:
    im, d = canvas()
    y = headline(d, "Local development", "The same runner", "over a file on your laptop.")
    steps = [("make stage-data", "downloads the pinned datasets once into data/cache, writes Parquet to data/stage"),
             ("pvsweep_synth plan · render", "scenario-first synthetic records: 13 kinds, 5 channels, anchored on real cases, rendered by GPT or Claude, validated, hashed"),
             ("pvsweep_runner sweep --backend local", "DuckDB file with the same schemas and views; models on Foundry or the Anthropic API"),
             ("pvsweep_runner.evaluate · compare", "metrics per run, confusion by scenario kind, cost at list prices, JSONL export for Foundry"),
             ("pvsweep_runner.snapshot", "copies a Snowflake or Databricks run into a local file"),
             ("scripts/run_app_local.sh", "the review app over the local file")]
    for i, (t, s) in enumerate(steps):
        bx = 96 + (i % 2) * 880
        by = y + (i // 2) * 140
        card(d, (bx, by, bx + 850, by + 122), t, [s], title_size=26, body_size=22)
    return finish(im, d, n)


def f30(n: int) -> Image.Image:
    im, d = canvas()
    y = headline(d, "Evaluation data", "450 records with known answers,", "anchored on real cases.")
    card(d, (96, y, 700, y + 300), "Scenario first", ["13 scenario kinds: new, in the safety database, in the queue, follow-ups, planned procedure, other MAH, no PV content…",
                                                      "5 channels · 2 generators (GPT, Claude) · every text carries its scenario hash"], tag="PLAN")
    card(d, (740, y, 1280, y + 300), "Anchored on FAERS", ["93 scenarios reuse a real case: same substance, sex, age, initials, dates", "so lookalikes and follow-ups are real, not invented"], tag="GROUND TRUTH")
    card(d, (1320, y, 1824, y + 300), "Public data only", ["FAERS (CC0) and VAERS (CC0 / Apache 2.0) at pinned revisions", "MedDRA and the IME list bring-your-own; demo lists instead"], tag="LICENCES")
    bullets(d, ["The gold record holds screening class, match outcome, causality, patient fields, seriousness and day 0 for every record."], 96, y + 340, 1700, 30)
    return finish(im, d, n)


def f32(n: int) -> Image.Image:
    im, d = canvas()
    y = headline(d, "Results · round 3 · 450 records", "Measured,", "not assumed.")
    rows = [("", "GPT (gpt-5-4-mini)", "Claude on Foundry (Haiku + Sonnet)"), ("Screening recall / precision", "0.997 / 1.0", "0.976 / 0.997"),
            ("Extraction valid", "0.995", "1.000"), ("Causality statement", "0.901", "0.938"), ("Seriousness", "0.968", "0.973"),
            ("Matching outcome", "0.835", "0.954"), ("Latency, matching per record", "14 s", "32 s at 50K TPM"), ("Model cost per sweep", "about $11", "about $11")]
    for i, (a, b, c) in enumerate(rows):
        yy = y + i * 50
        f = load(MONO, 22) if i == 0 else load(SANS, 30)
        col = GOLD if i == 0 else INK
        d.text((96, yy), a, font=f, fill=col)
        d.text((760, yy), b, font=f, fill=col)
        d.text((1240, yy), c, font=f, fill=col)
        if i == 0:
            d.line([(96, yy + 40), (1824, yy + 40)], fill=LINE)
    return finish(im, d, n)


def f33(n: int) -> Image.Image:
    im, d = canvas()
    y = headline(d, "Caveats", "What the numbers", "do not say.")
    bullets(d, ["The texts are synthetic. Real notes are messier, multilingual and longer; a pilot with real reviewers is the test that matters.",
                "GPT ran on a small model throughout; Claude matched with its large one. A tier-matched GPT run is the first thing to do next.",
                "The hosted path is proven on 8-record samples on both platforms; the 450-record numbers come from the in-process agent.",
                "Gold timing labels disagree with planted dates on 71 of 120 records; the overdue check now derives the expected flag from the dates.",
                "Records the agent judges already received never reach a reviewer: a sample of those belongs in production."],
            96, y, 1700, 30, gap=18)
    return finish(im, d, n)


def f34(n: int) -> Image.Image:
    im, d = canvas()
    y = headline(d, "Path to production", "What would change", "for a real deployment.")
    items = ["Connectors to the real source systems and a real safety database extract instead of FAERS",
             "Network isolation: Foundry, hosted agents through a customer VNet, private registry; Private Link on the data platform",
             "Data residency settled per step, with a DPA and transfer assessment where needed",
             "Licensed MedDRA with LLT coding; multilingual intake",
             "Azure API Management in front of the models: quotas, routing, central logging",
             "Computer system validation proportionate to risk (GAMP 5, CSA), change control on prompts, models and agent versions",
             "A pilot with real reviewers to measure the business KPIs the POC only simulates"]
    bullets(d, items, 96, y, 1700, 30, gap=14)
    return finish(im, d, n)


def f35(n: int) -> Image.Image:
    im, d = canvas()
    y = headline(d, "Everything in the box", "In the repository,", "today.")
    left = ["Definition with the regulatory grounding (GVP VI, ICH E2D)", "Architecture with 15 decision records and a spike log",
            "Business case with its assumptions table", "Matching error analysis and comparison reports", "Prompts and JSON schemas under version", "Synthetic data generator + 450 records with ground truth",
            "Runner: local, Snowflake, Databricks backends", "Hosted agents for GPT and Claude, one image", "Findings, priority, case intake package, QC sample"]
    right = ["Snowflake and Databricks SQL, migrations, loads, sync", "Review apps: Streamlit in Snowflake and a Databricks App",
             "Container Apps job, Key Vault, identities, budget", "Three Foundry evaluators, evaluate and compare tools",
             "Snapshot of cloud runs into local files", "CI and OIDC deployment workflows, 69 tests", "Operational notes for every lesson learned",
             "This video's script and the scripts that rebuild it"]
    bullets(d, left, 96, y, 840, 26, gap=8)
    bullets(d, right, 980, y, 840, 26, gap=8)
    return finish(im, d, n)


def f_errors(n: int) -> Image.Image:
    im, d = canvas()
    y = headline(d, "The error analysis", "Every disagreement classified,", "every fix traced to a cause.")
    card(d, (96, y, 900, y + 300), "37 disagreements, six causes",
         ["blocking cut the true case out of the candidates (7)", "agent dismissed an offered candidate after its own search found nothing (7)",
          "lookalikes accepted (8) · right case, wrong follow-up label (8)", "debatable gold on FAERS twins (4) · rate limits (3)"], tag="ROUND 1 · GPT", body_size=23)
    card(d, (940, y, 1824, y + 300), "Matching accuracy, run by run",
         ["0.71 first run · 0.91 with a country and date rule", "0.69 when an exact-key pass offered lookalikes to every record",
          "0.84 (GPT) and 0.96 (Claude) with patient initials and prompt v3"], tag="TRAJECTORY", body_size=23)
    rows = [("", "records", "GPT", "Claude"), ("Already in the safety database", "47", "0.447", "0.795"),
            ("Significant follow-up", "28", "0.393", "1.000"), ("Non-significant follow-up", "18", "0.333", "0.750")]
    for i, (a, b, c, e) in enumerate(rows):
        yy = y + 330 + i * 40
        f = load(MONO, 20) if i == 0 else load(SANS, 26)
        col = GOLD if i == 0 else INK
        d.text((96, yy), a, font=f, fill=col)
        d.text((700, yy), b, font=f, fill=col)
        d.text((900, yy), c, font=f, fill=col)
        d.text((1100, yy), e, font=f, fill=col)
        if i == 0:
            d.line([(96, yy + 32), (1300, yy + 32)], fill=LINE)
    d.text((1340, y + 335), "Claude confirms a candidate by reading", font=load(SANS, 23), fill=MUTED)
    d.text((1340, y + 365), "its case history; GPT rejects it when", font=load(SANS, 23), fill=MUTED)
    d.text((1340, y + 395), "its own search returns nothing.", font=load(SANS, 23), fill=MUTED)
    d.text((1340, y + 435), "docs/ops/comparison-round3.md · matching-analysis.md", font=load(MONO, 18), fill=GOLD)
    return finish(im, d, n)


def f_roles(n: int) -> Image.Image:
    im, d = canvas()
    y = headline(d, "Least privilege", "Seven roles.", "No run-time role updates or deletes.")
    roles = [("PVSWEEP_ADMIN", "owns the objects; deployment only", GOLD), ("PVSWEEP_PIPELINE", "the runner: reads sources, writes results and audit", GOLD),
             ("PVSWEEP_AGENT", "the hosted agents: six secure views, nothing else", GREEN), ("PVSWEEP_REVIEW_APP", "the review app's role", (155, 176, 196)),
             ("PVSWEEP_REVIEWER", "reviewers: review tables, patient fields unmasked", (155, 176, 196)),
             ("PVSWEEP_ANALYST", "report views only, masked by design", (155, 176, 196)), ("PVSWEEP_CI", "pipeline and agent rights on a cloned database", MUTED)]
    for i, (t, s, c) in enumerate(roles):
        bx = 96 + (i % 4) * 440
        by = y + (i // 4) * 150
        d.rounded_rectangle([bx, by, bx + 420, by + 130], radius=14, fill=CARD, outline=LINE)
        d.rectangle([bx, by + 12, bx + 5, by + 118], fill=c)
        d.text((bx + 24, by + 20), t, font=load(MONO, 22), fill=c)
        for j, ln in enumerate(wrap(d, s, load(SANS, 22), 380)):
            d.text((bx + 24, by + 58 + j * 28), ln, font=load(SANS, 22), fill=MUTED)
    bullets(d, ["Append-only tables: the only UPDATE any run-time role holds is the runner closing its own SWEEP.RUN row (V008).",
                "Databricks: no key material at all; runner and agents use Entra tokens, the agents are workspace service principals.",
                "Stated gap: Unity Catalog has no insert-only privilege, so append-only is not enforced there yet; delta.appendOnly is the documented fix."],
            96, y + 320, 1700, 26, gap=10)
    return finish(im, d, n)


def f_decisions(n: int) -> Image.Image:
    im, d = canvas()
    y = headline(d, "Architecture decisions · 6 of 15", "Why it is built this way,", "with the alternative and the reason.")
    items = [("ADR-001 · An Azure job, not code inside the platform", "orchestration independent of the data platform: one package on Snowflake, Databricks and a local file; the platform stays the system of record"),
             ("ADR-002 · Foundry, not Snowflake Cortex", "both providers behind one identity model, the agent runtime, filters, evaluations and quota; not bound to one data platform"),
             ("ADR-008 · Synchronous calls, bounded concurrency", "Claude on Foundry has no Message Batches; the comparison needs the same mode on both"),
             ("ADR-009 · Screening and extraction are single calls", "one input, one structured output, nothing to decide: an agent adds cost and variance"),
             ("ADR-010 · The decision is a strict tool's argument", "works identically on both providers; structured output via the framework's Anthropic client is undocumented"),
             ("ADR-012 · Reused sessions, a fresh thread per invocation", "hosted compute is billed per session, idle time included; reuse is safe only with fresh state")]
    for i, (t, s) in enumerate(items):
        bx = 96 + (i % 2) * 880
        by = y + (i // 2) * 150
        card(d, (bx, by, bx + 850, by + 132), t, [s], title_size=26, body_size=22)
    return finish(im, d, n)


def f_parity(n: int) -> Image.Image:
    im, d = canvas()
    y = headline(d, "Same code, two hosting paths", "Anthropic's API or Foundry:", "within half a point.")
    rows = [("", "Claude via Anthropic API", "Claude on Foundry"), ("Matching accuracy", "0.956", "0.954"), ("Screening recall", "0.968", "0.976"),
            ("Causality statement", "0.929", "0.938"), ("Extraction valid", "1.000", "1.000")]
    for i, (a, b, c) in enumerate(rows):
        yy = y + i * 50
        f = load(MONO, 22) if i == 0 else load(SANS, 30)
        col = GOLD if i == 0 else INK
        d.text((96, yy), a, font=f, fill=col)
        d.text((640, yy), b, font=f, fill=col)
        d.text((1140, yy), c, font=f, fill=col)
        if i == 0:
            d.line([(96, yy + 40), (1500, yy + 40)], fill=LINE)
    bullets(d, ["What Foundry adds: Entra ID instead of an API key, EU billing, and the audit trail in the data platform.",
                "Claude's recall loss is a format failure: 14 records answered invalid JSON twice and were logged, not routed. Fix: retry on the large model.",
                "Prompt caching on the Claude system prompt: 1.9 M cached input tokens in round 3; cache reads do not count against the Foundry quota."],
            96, y + 290, 1700, 26, gap=10)
    return finish(im, d, n)


def f_value(n: int) -> Image.Image:
    im, d = canvas()
    y = headline(d, "The business case", "327 hours a month by hand,", "24 to 39 with the sweep.")
    rows = [("8,000 records / month · 3 % with PV content", "Manual", "GPT", "Claude"), ("Findings to review", "240 + re-reading everything", "102", "43"),
            ("Reviewer hours / month", "327 h, about 2 FTE", "38.5 h", "23.8 h"), ("People cost / month", "EUR 19,600", "EUR 2,312", "EUR 1,429"),
            ("Model cost / month", "—", "about $15", "about $15"), ("Accuracy on records PV already holds", "—", "0.60", "0.86")]
    for i, (a, b, c, e) in enumerate(rows):
        yy = y + i * 50
        f = load(MONO, 22) if i == 0 else load(SANS, 28)
        col = GOLD if i == 0 else INK
        d.text((96, yy), a, font=f, fill=col)
        d.text((900, yy), b, font=f, fill=col)
        d.text((1330, yy), c, font=f, fill=col)
        d.text((1580, yy), e, font=f, fill=col)
        if i == 0:
            d.line([(96, yy + 40), (1824, yy + 40)], fill=LINE)
    bullets(d, ["Cadence: a weekly sweep finds an unforwarded serious case with at least 8 of its 15 days left; a monthly one finds most after the deadline. Same model cost.",
                "Assumptions A1–A15 with ranges; 2 % false positives on real text still keeps the sweep under a quarter of the manual effort."],
            96, y + 340, 1700, 26, gap=10)
    return finish(im, d, n)


def f_options(n: int) -> Image.Image:
    im, d = canvas()
    y = headline(d, "Data residency", "Three options,", "and the decision asked of the sponsor.")
    opts = [("A · GPT throughout, EU data zone", ["simplest residency", "38.5 h of review a month; weaker follow-up labels"]),
            ("B · Claude throughout", ["best measured matching and causality", "needs a transfer assessment or pseudonymisation; Claude on Foundry is Global Standard or US zone only, operational data outside Azure"]),
            ("C · GPT screens in the EU, Claude matches", ["pseudonymised candidates only go to Claude", "highest recall plus the best matching", "two providers to operate and validate; pseudonymisation design unproven"])]
    for i, (t, lines) in enumerate(opts):
        bx = 96 + i * 585
        card(d, (bx, y, bx + 560, y + 290), t, lines, title_size=26, body_size=22)
    bullets(d, ["Decisions asked: approve phase 1 and a phase-2 pilot on a named channel · set the residency position (EU-only, or a transfer assessment allowed) · name the QPPV delegate and the QA contact.",
                "Keep both providers through phase 1; the agent code is identical on both."],
            96, y + 330, 1700, 26, gap=10)
    return finish(im, d, n)


def shared(n: int):
    fn = {0: frame_00, 1: frame_01, 5: frame_02, 42: frame_10}[n]
    im = fn(None, TOTAL)
    # repaint the footer caption and counter for the long script
    d = ImageDraw.Draw(im)
    from make_demo_frames import FOOTER_H
    d.rectangle([0, H - FOOTER_H - 2, W, H], fill=(11, 11, 14))
    d.rectangle([W - 320, 30, W, 90], fill=(11, 11, 14))   # the short demo's own counter
    for x in range(0, W, 120):
        d.line([(x, H - FOOTER_H - 2), (x, H)], fill=(26, 26, 32), width=1)
        if x >= W - 320:
            d.line([(x, 30), (x, 90)], fill=(26, 26, 32), width=1)
    footer(im, d, "" if KARAOKE else CAPS.get(n, ""), None, n, TOTAL)
    return im


SHOT_MAP = {14: ("06-*.jpg", "Snowflake · review app"), 15: ("07-decision-flow.gif", "Snowflake · recording a decision"),
            18: ("05-*.jpg", "Snowflake · the agent's views"), 19: ("03-*.jpg", "Microsoft Foundry · model deployments"),
            20: ("04-*.jpg", "Microsoft Foundry · hosted agents"), 25: ("09a-*.jpg", "Azure Databricks · Unity Catalog"),
            26: ("09b-*.jpg", "Azure Databricks · the review app"), 34: ("08-*.jpg", "Microsoft Foundry · evaluation")}

# frame number -> slide function (functions keep the number they had in the 37-frame script; the map is the truth)
SLIDES = {2: f02, 3: f03, 4: f04, 6: f06, 7: f07, 8: f08, 9: f09, 10: f10, 11: f_errors, 12: f11, 13: f12, 16: f15, 17: f16,
          21: f20, 22: f21, 23: f22, 24: f_roles, 27: f_decisions, 28: f25, 29: f26, 30: f27, 31: f28, 32: f29, 33: f30,
          35: f32, 36: f_parity, 37: f33, 38: f_value, 39: f_options, 40: f34, 41: f35}

def render(n: int) -> Image.Image:
    if n in SLIDES:
        return SLIDES[n](n)
    if n in SHOT_MAP:
        pattern, section = SHOT_MAP[n]
        files = sorted(SHOTS.glob(pattern))
        src = Image.open(files[0])
        if pattern.endswith(".gif"):
            src.seek(src.n_frames - 1)
        return place_shot(n, src, section, "" if KARAOKE else CAPS.get(n, ""), TOTAL)
    return shared(n)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    wanted = [int(x) for x in args.only.split(",") if x.strip()] or list(range(TOTAL))
    for n in wanted:
        im = render(n)
        im.save(OUT / f"{n:02d}.png", optimize=True)
        print(OUT / f"{n:02d}.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
