# Demo script

One source for the outputs: the narrated MP4 embedded in the README (captions, narration,
karaoke subtitles), its silent twin, and an optional GIF for places that cannot embed a video. Each frame has the screen to capture, the
caption shown on screen and the narration. Narration runs at about 2.5 words per second; the frame
lasts as long as its narration plus half a second.

| # | Screen | Caption | Narration | ~s |
|---|---|---|---|---|
| 0 | Title card: product name and "A Microsoft AI Foundry, Snowflake and Databricks POC" | Models propose. A person decides. | This is the short version. Pharmacovigilance Sweep: an agentic proof of concept on Microsoft Foundry, with Snowflake or Azure Databricks as the data platform. Models propose; a person decides. The detailed walkthrough is linked in the description. | 14 |
| 1 | Slide: five channel icons (medical information, CRM, patient support, quality complaints, social media) with a 15-day clock | Side effects are mentioned where pharmacovigilance does not look | A pharmacovigilance department only sees what reaches it. Side effects are mentioned every day in medical information calls, sales reps' notes, patient programmes, quality complaints and social media. Under EU rules the company is responsible for all of them, and the fifteen-day clock for a serious case starts the day anyone in the company first hears of it. | 20 |
| 2 | Slide: the six steps as a horizontal flow (screen, extract, rules, match, finding, reconcile) | Re-read every record. Keep what PV never received. | The sweep re-reads those records after the fact. It screens each one for an adverse event, extracts the case facts with their evidence, applies the regulatory rules, asks an agent whether pharmacovigilance already has the case, and turns what is new into a prioritised finding with a proposed intake package. Vendor logs are reconciled on the way. | 20 |
| 3 | Foundry portal: model deployments of the project (gpt-5-4-mini, claude-haiku-5-5, claude-sonnet-5-5) | One Foundry project, two providers, Entra ID only | Everything runs on one Microsoft Foundry project: GPT in the EU data zone and Claude, deployed from Bicep and called with Entra ID. No API keys anywhere. | 12 |
| 4 | Foundry portal: hosted agents pvsweep-matcher-gpt and pvsweep-matcher-claude with their versions | The matching agent runs as a hosted agent, with read-only tools | The matching step is a hosted agent in Foundry Agent Service, one per provider, with the same code. Its tools only read: the safety database, the intake queue and the vendor log. It never writes SQL and never sends anything. | 13 |
| 5 | Snowsight: the PVSWEEP database tree with AGENT_API expanded | The agent sees four secure views and nothing else | Snowflake holds the data, the results and the audit trail. The agent's credential can read the AGENT_API views and nothing else, and every model call is recorded with its tokens, latency and cost. | 12 |
| 6 | Review app in Snowflake: prioritised queue, one finding open with the proposed case intake package and the late-submission warning | Every routed record ends as a finding with a proposed intake package | The reviewer works a prioritised queue. Each finding carries the proposed case intake package: patient, product, event, seriousness, day zero, deadline and the match against what PV already holds. | 13 |
| 7 | Recorded clip: checklist ticked, outcome D selected, "Record decision", confirmation message | The reviewer confirms day 0 and the outcome; nothing is closed by a model | The reviewer confirms day zero and records the outcome. That writes the confirmed package and, when the deadline was missed, a compliance finding with a root cause. Nothing is closed by a model. | 12 |
| 8 | Foundry portal: evaluation run report with the three custom evaluators | 450 synthetic records, graded by custom evaluators in Foundry | Quality is measured, not assumed. Four hundred and fifty synthetic records with known answers, graded by custom evaluators in Foundry: routing, matching outcome and causality statement, for both providers. | 13 |
| 9 | Databricks: Catalog Explorer with the pvsweep schemas and the load_stage volume, then the Databricks App showing the reconciliation | Same tables, same app, on Azure Databricks | The same platform runs on Azure Databricks: the same tables in Unity Catalog, the same runner and agents, the same review app, with the processed results copied over rather than recomputed. | 12 |
| 10 | Closing card: results table (screening recall, matching, cost per sweep for GPT and Claude) and the repository URL | github.com/cesarzea/pharmacovigilance-sweep | On the same records, screening recall is above ninety-seven percent for both providers; matching reaches eighty-four percent with GPT and ninety-five with Claude; a full sweep costs about eleven dollars in model calls. Everything is deployable from scratch by the scripts in the repository. This was the short version: for the full walkthrough, how it does it, how it is built, how it is measured and what it is worth, follow the link in the description. | 26 |

Total: about 3 minutes narrated with the Gemini voice.

## Production notes

- Captions are also the subtitle track (SRT); narration is one audio clip per frame (Gemini TTS,
  English; a Spanish narration can reuse the same frames).
- Screens 3, 4 and 8 need an Azure sign-in in the capture browser; 5, 6, 7 Snowsight; 9 Databricks.
- Frames 1, 2 and 10 are rendered slides, not screenshots.
- Figures come from docs/ops/spike-log.md (round 3 and the Foundry path) and must be updated together
  with them.
