#!/usr/bin/env python3
"""Put one or more MCP servers in a Foundry toolbox that agents can share.

The toolbox's MCP tools use the same OAuth connections as directly attached
tools, so users sign in to each service once either way. The script also
creates the connection agents use to call the toolbox as the signed-in user
(named <toolbox>-user). It's safe to rerun: a new toolbox version is created
and made the default only when the tools change.

Example:

    python scripts/create_toolbox.py --resource-group rg-mcp-agent --service github --service zoominfo
"""

from __future__ import annotations

import argparse
import sys
from urllib.parse import quote

import requests
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import MCPToolboxTool
from azure.core.exceptions import ResourceNotFoundError
from azure.identity import AzureCliCredential

from common import SERVICES, deployment_outputs, require_service, with_retry

TOOLBOX_AUDIENCE = "https://ai.azure.com"
CONNECTION_API_VERSION = "2025-06-01"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--resource-group", required=True)
    parser.add_argument(
        "--service",
        required=True,
        action="append",
        choices=sorted(SERVICES),
        help="Repeat to put several MCP servers in one toolbox",
    )
    parser.add_argument("--toolbox-name", default="mcp-tools")
    parser.add_argument("--deployment-name", default="main")
    parser.add_argument("--subscription", help="Defaults to the active Azure CLI subscription")
    return parser.parse_args()


def toolbox_url(project_endpoint: str, toolbox_name: str) -> str:
    """Toolbox MCP endpoint. Prompt agents need the audience in the URL."""
    return (
        f"{project_endpoint}/toolboxes/{toolbox_name}/mcp"
        f"?api-version=v1&audience={quote(TOOLBOX_AUDIENCE, safe='')}"
    )


def toolbox_connection_id(project_id: str, toolbox_name: str) -> str:
    return f"{project_id}/connections/{toolbox_name}-user"


def project_id_from(outputs: dict, services: list[str]) -> str:
    """Derive the project's resource ID from a deployed connection's ID."""
    connection_id = outputs[SERVICES[services[0]]["outputs"][f"{services[0].upper()}_CONNECTION_ID"]]
    return connection_id.split("/connections/")[0]


def ensure_toolbox(client: AIProjectClient, name: str, tools: list[dict]) -> None:
    try:
        toolbox = with_retry(lambda: client.toolboxes.get(name))
        current = with_retry(lambda: client.toolboxes.get_version(name, toolbox.default_version))
        current_tools = [tool.as_dict() for tool in current.tools]
    except ResourceNotFoundError:
        current_tools = []

    if current_tools == tools:
        print(f"Toolbox '{name}' is already up to date.")
        return

    version = with_retry(
        lambda: client.toolboxes.create_version(
            name=name,
            tools=[MCPToolboxTool(**{k: v for k, v in tool.items() if k != "type"}) for tool in tools],
        )
    )
    with_retry(lambda: client.toolboxes.update(name, default_version=version.version))
    print(f"Toolbox '{name}' version {version.version} is now the default.")


def ensure_toolbox_connection(credential: AzureCliCredential, connection_id: str, target: str) -> None:
    token = credential.get_token("https://management.azure.com/.default").token
    response = with_retry(
        lambda: requests.put(
            f"https://management.azure.com{connection_id}",
            params={"api-version": CONNECTION_API_VERSION},
            headers={"Authorization": f"Bearer {token}"},
            json={
                "properties": {
                    "authType": "UserEntraToken",
                    "category": "RemoteTool",
                    "target": target,
                    "audience": TOOLBOX_AUDIENCE,
                    "metadata": {"type": "generic_mcp", "audience": TOOLBOX_AUDIENCE},
                    "isSharedToAll": False,
                    "peRequirement": "NotRequired",
                }
            },
            timeout=60,
        )
    )
    if response.status_code not in (200, 201):
        raise RuntimeError(f"Creating the toolbox connection failed: {response.status_code} {response.text}")
    print(f"Toolbox connection '{connection_id.rsplit('/', 1)[-1]}' is configured.")


def main() -> None:
    args = parse_args()
    services = list(dict.fromkeys(args.service))
    outputs = deployment_outputs(args.resource_group, args.deployment_name, args.subscription)

    tools = []
    for service in services:
        settings = require_service(service, outputs)
        names = settings["outputs"]
        prefix = service.upper()
        tools.append(
            {
                "type": "mcp",
                "server_label": service,
                "server_url": outputs[names[f"{prefix}_MCP_URL"]],
                "project_connection_id": outputs[names[f"{prefix}_CONNECTION_ID"]],
                "require_approval": "never",
            }
        )

    credential = AzureCliCredential()
    project_endpoint = outputs["projectEndpoint"]
    client = AIProjectClient(endpoint=project_endpoint, credential=credential)
    ensure_toolbox(client, args.toolbox_name, tools)

    url = toolbox_url(project_endpoint, args.toolbox_name)
    connection_id = toolbox_connection_id(project_id_from(outputs, services), args.toolbox_name)
    ensure_toolbox_connection(credential, connection_id, url)

    print()
    print("To give an agent every tool in this toolbox, run:")
    print(f"  python scripts/deploy_agent.py --resource-group {args.resource_group} --service <service> --toolbox-name {args.toolbox_name}")
    print("Or add a tool directly to an agent in the Foundry portal (Add tool > Configured).")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 -- concise CLI error
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
