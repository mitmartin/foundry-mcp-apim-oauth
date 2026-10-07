#!/usr/bin/env python3
"""Create or update the prompt agent and attach the GitHub MCP tool.

The tool is attached directly to the agent. It points at the API Management
MCP endpoint and uses the Foundry OAuth connection from the Bicep deployment,
so each user signs in to GitHub once and every call runs as that user.

Example:

    python scripts/deploy_agent.py --resource-group rg-mcp-agent --github-org my-org
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import MCPTool, PromptAgentDefinition
from azure.identity import AzureCliCredential

from common import deployment_outputs, with_retry

DEFAULT_DEFINITION = Path(__file__).resolve().parent.parent / "agent" / "agent.yaml"
PLACEHOLDER = re.compile(r"\$\{([A-Z0-9_]+)\}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--resource-group", required=True)
    parser.add_argument("--deployment-name", default="main")
    parser.add_argument("--subscription", help="Defaults to the active Azure CLI subscription")
    parser.add_argument(
        "--github-org",
        required=True,
        help="GitHub organization the agent uses when the user doesn't name one",
    )
    parser.add_argument("--agent-name", help="Overrides the name in the definition file")
    parser.add_argument("--definition", type=Path, default=DEFAULT_DEFINITION)
    return parser.parse_args()


def render(definition_path: Path, values: dict[str, str]) -> dict:
    text = definition_path.read_text(encoding="utf-8")
    missing = sorted({name for name in PLACEHOLDER.findall(text) if name not in values})
    if missing:
        raise ValueError(f"No value for placeholders: {', '.join(missing)}")
    return yaml.safe_load(PLACEHOLDER.sub(lambda m: values[m.group(1)], text))


def build_tools(tool_configs: list[dict]) -> list[MCPTool]:
    tools = []
    for config in tool_configs:
        if config.get("type") != "mcp":
            raise ValueError(f"Unsupported tool type: {config.get('type')}")
        tools.append(
            MCPTool(
                server_label=config["server_label"],
                server_url=config["server_url"],
                project_connection_id=config["project_connection_id"],
                require_approval=config.get("require_approval", "always"),
            )
        )
    return tools


def main() -> None:
    args = parse_args()
    outputs = deployment_outputs(args.resource_group, args.deployment_name, args.subscription)
    definition = render(
        args.definition,
        {
            "MODEL_DEPLOYMENT_NAME": outputs["modelDeploymentName"],
            "GITHUB_MCP_URL": outputs["githubMcpUrl"],
            "GITHUB_CONNECTION_ID": outputs["githubConnectionId"],
            "GITHUB_ORG": args.github_org,
        },
    )
    agent_name = args.agent_name or definition["name"]

    client = AIProjectClient(
        endpoint=outputs["projectEndpoint"], credential=AzureCliCredential()
    )
    agent = with_retry(
        lambda: client.agents.create_version(
            agent_name=agent_name,
            definition=PromptAgentDefinition(
                model=definition["model"],
                instructions=definition["instructions"],
                tools=build_tools(definition.get("tools", [])),
            ),
        )
    )
    print(f"Deployed agent '{agent.name}' version {agent.version}.")
    print(f"Project endpoint: {outputs['projectEndpoint']}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 -- concise CLI error
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
