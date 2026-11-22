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
import subprocess
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
AZURE_AI_USER = "53ca6127-db72-4b80-b1b0-d745d6d5456d"  # lets the agent identity call the account's models with Entra ID


def grant_model_access(project: AIProjectClient, name: str, version: str, account_id: str) -> None:
    """The platform mints an identity per hosted agent; Claude on Foundry is called with that identity's token, so
    it needs Azure AI User on the Foundry account (the GPT path through the project endpoint does not)."""
    info = project.agents.get_version(agent_name=name, agent_version=version)
    principal = (info.get("instance_identity") or {}).get("principal_id")
    if not principal:
        print(f"{name}: no instance identity reported; skipping role assignment")
        return
    cmd = ["az", "role", "assignment", "create", "--assignee-object-id", principal, "--assignee-principal-type", "ServicePrincipal",
           "--role", AZURE_AI_USER, "--scope", account_id, "-o", "none", "--only-show-errors"]
    subprocess.run(cmd, check=True)
    print(f"{name}: Azure AI User granted to agent identity {principal}")


def deploy(project: AIProjectClient, image: str, provider: str, deployment: str, resource: str,
           project_endpoint: str, cpu: str, memory: str, snowflake_account: str = "",
           snowflake_connection: str = "", account_id: str = "") -> str:
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
            if account_id:
                grant_model_access(project, name, version.version, account_id)
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
    ap.add_argument("--account-id", default="", help="ARM id of the Foundry account, for the agent identity's model role")
    ap.add_argument("--roles-only", action="store_true", help="only (re)grant the model role to the latest active versions")
    args = ap.parse_args()
    if len(args.provider) != len(args.deployment):
        ap.error("--provider and --deployment must be given the same number of times")

    resource = args.project_endpoint.split("//")[1].split(".")[0]
    project = AIProjectClient(endpoint=args.project_endpoint, credential=DefaultAzureCredential())
    for provider, deployment in zip(args.provider, args.deployment, strict=True):
        if args.roles_only:
            name = f"{AGENT_PREFIX}-{provider}"
            latest = max(project.agents.list_versions(agent_name=name), key=lambda v: int(v.version))
            grant_model_access(project, name, latest.version, args.account_id)
            continue
        deploy(project, args.image, provider, deployment, resource, args.project_endpoint, args.cpu, args.memory,
               args.snowflake_account, args.snowflake_connection, args.account_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
