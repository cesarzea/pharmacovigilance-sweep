"""Register the code-based evaluators in the Foundry project and run an evaluation on an exported sweep.

    uv run --with "azure-ai-projects>=2.8" --with azure-identity --with openai python -I scripts/foundry_evaluate.py \
        --project-endpoint https://<account>.services.ai.azure.com/api/projects/<project> \
        --deployment gpt-5-4-mini --data data/eval/<run>.jsonl --name "sweep <run> gpt"

The evaluators are deterministic grade() functions (no model), the same definitions as
runner/pvsweep_runner/evaluate.py, so Foundry shows the per-provider comparison with one source of
truth. Custom evaluator definitions are a preview feature (Foundry-Features: Evaluations=V1Preview).
"""

from __future__ import annotations

import argparse
import sys
import time

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import EvaluatorCategory, EvaluatorDefinitionType
from azure.identity import DefaultAzureCredential
from openai.types.evals.create_eval_jsonl_run_data_source_param import CreateEvalJSONLRunDataSourceParam, SourceFileID

ROUTED = ("ADVERSE_EVENT", "SPECIAL_SITUATION")

EVALUATORS = {
    "pvsweep_screening_routing": {
        "display_name": "PV Sweep: screening routing",
        "description": "1.0 when a record with PV content was routed to PV assessment (or a record without it was not); "
                       "screening recall when averaged over records that have PV content.",
        "code": '''
ROUTED = ("ADVERSE_EVENT", "SPECIAL_SITUATION")

def grade(sample: dict, item: dict) -> float:
    gold = item.get("gold_screening") in ROUTED
    pred = item.get("predicted_screening") in ROUTED
    return 1.0 if gold == pred else 0.0
''',
        "schema": {"gold_screening": {"type": "string"}, "predicted_screening": {"type": "string"}},
    },
    "pvsweep_matching_outcome": {
        "display_name": "PV Sweep: matching outcome",
        "description": "1.0 when the matching decision equals the expected outcome for the record.",
        "code": '''
def grade(sample: dict, item: dict) -> float:
    pred = item.get("predicted_match")
    if pred is None:
        return 0.0
    return 1.0 if pred == item.get("gold_match") else 0.0
''',
        "schema": {"gold_match": {"type": "string"}, "predicted_match": {"type": ["string", "null"]}},
    },
    "pvsweep_causality_statement": {
        "display_name": "PV Sweep: causality statement",
        "description": "1.0 when the extracted reporter causality statement equals the planted one.",
        "code": '''
def grade(sample: dict, item: dict) -> float:
    scores = item.get("scores") or {}
    if "causality" not in scores:
        return 0.0
    return float(scores.get("causality", 0))
''',
        "schema": {"scores": {"type": "object"}},
    },
}


def register(project: AIProjectClient, deployment: str) -> None:
    for name, spec in EVALUATORS.items():
        project.evaluators.create_version(
            name=name,
            evaluator_version={
                "name": name,
                "categories": [EvaluatorCategory.QUALITY],
                "display_name": spec["display_name"],
                "description": spec["description"],
                "definition": {
                    "type": EvaluatorDefinitionType.CODE,
                    "code_text": spec["code"].strip() + "\n",
                    "init_parameters": {
                        "type": "object",
                        "properties": {"deployment_name": {"type": "string"}, "pass_threshold": {"type": "number"}},
                        "required": ["deployment_name", "pass_threshold"],
                    },
                    "metrics": {"result": {"type": "continuous", "desirable_direction": "increase", "min_value": 0.0, "max_value": 1.0}},
                    "data_schema": {"type": "object", "required": ["item"],
                                    "properties": {"item": {"type": "object", "properties": spec["schema"]}}},
                },
            },
            headers={"Foundry-Features": "Evaluations=V1Preview"},
        )
        print(f"registered evaluator {name}")


def run_evaluation(project: AIProjectClient, deployment: str, data_path: str, name: str) -> int:
    openai_client = project.get_openai_client()
    dataset = project.datasets.upload_file(name=f"pvsweep-eval-{int(time.time())}", version="1", file_path=data_path)
    data_source_config = {
        "type": "custom",
        "item_schema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string"}, "record_id": {"type": "string"}, "kind": {"type": "string"},
                "gold_screening": {"type": "string"}, "predicted_screening": {"type": "string"},
                "gold_match": {"type": "string"}, "predicted_match": {"type": ["string", "null"]},
                "gold_causality": {"type": ["string", "null"]}, "scores": {"type": "object"},
            },
            "required": ["record_id", "gold_screening", "predicted_screening", "gold_match"],
        },
    }
    testing_criteria = [
        {"type": "azure_ai_evaluator", "name": n, "evaluator_name": n,
         "initialization_parameters": {"deployment_name": deployment, "pass_threshold": 0.5}}
        for n in EVALUATORS
    ]
    ev = openai_client.evals.create(name=name, data_source_config=data_source_config, testing_criteria=testing_criteria)
    run = openai_client.evals.runs.create(
        eval_id=ev.id, name=name,
        data_source=CreateEvalJSONLRunDataSourceParam(type="jsonl", source=SourceFileID(type="file_id", id=dataset.id)),
    )
    print(f"evaluation {ev.id}, run {run.id}: waiting", flush=True)
    while True:
        run = openai_client.evals.runs.retrieve(run_id=run.id, eval_id=ev.id)
        if run.status in ("completed", "failed", "canceled"):
            break
        time.sleep(10)
    print(f"status: {run.status}")
    for c in run.per_testing_criteria_results or []:
        total = (c.passed or 0) + (c.failed or 0)
        print(f"  {c.testing_criteria:32} passed {c.passed}/{total}")
    print(f"report: {run.report_url}")
    return 0 if run.status == "completed" else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-endpoint", required=True)
    ap.add_argument("--deployment", required=True, help="any model deployment name; required by the API, not called")
    ap.add_argument("--data", default=None, help="JSONL exported by pvsweep_runner.evaluate --export")
    ap.add_argument("--name", default="pvsweep sweep")
    ap.add_argument("--register-only", action="store_true")
    args = ap.parse_args()
    project = AIProjectClient(endpoint=args.project_endpoint, credential=DefaultAzureCredential())
    register(project, args.deployment)
    if args.register_only or not args.data:
        return 0
    return run_evaluation(project, args.deployment, args.data, args.name)


if __name__ == "__main__":
    sys.exit(main())
