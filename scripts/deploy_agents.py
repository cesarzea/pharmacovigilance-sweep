"""Create (or update) the Pharmacovigilance Sweep hosted agents in Foundry Agent Service.

Idempotent: every run creates a new immutable agent version from the given image tag and waits
until it is active. Run after `make deploy` and `make build-agent`.

    uv run --with azure-ai-projects --with azure-identity python -I scripts/deploy_agents.py \
        --project-endpoint https://<account>.services.ai.azure.com/api/projects/<project> \
        --image <registry>.azurecr.io/pvsweep-agent:<tag> \
        --provider gpt --deployment gpt-5-4-mini [--provider claude --deployment claude-haiku-5-5]
"""

from __future__ import annotations

import argparse
import sys
import time

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    AgentEndpointProtocol,
    ContainerConfiguration,
    HostedAgentDefinition,
    ProtocolVersionRecord,
)
from azure.identity import DefaultAzureCredential

AGENT_PREFIX = "pvsweep-matcher"


def deploy(project: AIProjectClient, image: str, provider: str, deployment: str, resource: str,
           project_endpoint: str, cpu: str, memory: str, snowflake_account: str = "",
           snowflake_connection: str = "") -> str:
    name = f"{AGENT_PREFIX}-{provider}"
    # FOUNDRY_* and AGENT_* names are reserved by the platform (it injects FOUNDRY_PROJECT_ENDPOINT).
    env = {
        "PYTHONNOUSERSITE": "1",
        "MODEL_PROVIDER": provider,
        "MODEL_DEPLOYMENT_NAME": deployment,
        "PVSWEEP_PROJECT_ENDPOINT": project_endpoint,
        "PVSWEEP_FOUNDRY_RESOURCE": resource,
    }
    if snowflake_account and snowflake_connection:
        # The platform resolves the placeholder from the project connection at runtime
        # (infra/modules/connections.bicep), so the key is never part of the agent definition.
        env["PVSWEEP_SNOWFLAKE_ACCOUNT"] = snowflake_account
        env["PVSWEEP_SNOWFLAKE_PRIVATE_KEY"] = "${{connections." + snowflake_connection + ".credentials.private_key}}"
    version = project.agents.create_version(
        agent_name=name,
        definition=HostedAgentDefinition(
            protocol_versions=[ProtocolVersionRecord(protocol=AgentEndpointProtocol.INVOCATIONS, version="2.0.0")],
            cpu=cpu,
            memory=memory,
            container_configuration=ContainerConfiguration(image=image),
            environment_variables=env,
        ),
        description=f"Pharmacovigilance Sweep matching agent on {provider} ({deployment})",
    )
    print(f"{name}: version {version.version} created, waiting for provisioning", flush=True)
    deadline = time.time() + 20 * 60
    while time.time() < deadline:
        info = project.agents.get_version(agent_name=name, agent_version=version.version)
        status = info["status"]
        if status == "active":
            print(f"{name}: version {version.version} active")
            return name
        if status == "failed":
            raise SystemExit(f"{name}: provisioning failed: {info.get('error')}")
        time.sleep(10)
    raise SystemExit(f"{name}: still '{status}' after 20 minutes")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-endpoint", required=True)
    ap.add_argument("--image", required=True)
    ap.add_argument("--provider", action="append", choices=["gpt", "claude"], required=True)
    ap.add_argument("--deployment", action="append", required=True, help="one per --provider, same order")
    ap.add_argument("--cpu", default="0.5")
    ap.add_argument("--memory", default="1Gi")
    ap.add_argument("--snowflake-account", default="")
    ap.add_argument("--snowflake-connection", default="", help="project connection holding the agent's private key")
    args = ap.parse_args()
    if len(args.provider) != len(args.deployment):
        ap.error("--provider and --deployment must be given the same number of times")

    resource = args.project_endpoint.split("//")[1].split(".")[0]
    project = AIProjectClient(endpoint=args.project_endpoint, credential=DefaultAzureCredential())
    for provider, deployment in zip(args.provider, args.deployment, strict=True):
        deploy(project, args.image, provider, deployment, resource, args.project_endpoint, args.cpu, args.memory,
               args.snowflake_account, args.snowflake_connection)
    return 0


if __name__ == "__main__":
    sys.exit(main())
