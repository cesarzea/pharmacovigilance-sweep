"""Agent Framework chat clients for both providers in Microsoft Foundry, Entra ID only."""

from __future__ import annotations

from azure.identity import DefaultAzureCredential, get_bearer_token_provider

ENTRA_SCOPE = "https://ai.azure.com/.default"


def make_client(provider: str, deployment: str, *, project_endpoint: str | None = None, resource: str | None = None):
    if provider == "claude-direct":
        # Anthropic API with the user's key (ANTHROPIC_API_KEY): local development only.
        import os

        from agent_framework.anthropic import AnthropicClient
        from anthropic import AsyncAnthropic

        ws = os.environ.get("ANTHROPIC_WORKSPACE_ID")
        headers = {"anthropic-workspace-id": ws} if ws else {}
        return AnthropicClient(model=deployment, anthropic_client=AsyncAnthropic(max_retries=5, default_headers=headers))
    credential = DefaultAzureCredential()
    if provider == "claude":
        from agent_framework.anthropic import AnthropicFoundryClient

        if not resource:
            raise ValueError("resource is required for Claude")
        return AnthropicFoundryClient(resource=resource, model=deployment,
                                      azure_ad_token_provider=get_bearer_token_provider(credential, ENTRA_SCOPE))
    from agent_framework.foundry import FoundryChatClient

    if not project_endpoint:
        raise ValueError("project_endpoint is required for GPT")
    return FoundryChatClient(project_endpoint=project_endpoint, model=deployment, credential=credential)
