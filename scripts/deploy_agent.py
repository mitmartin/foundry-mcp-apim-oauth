#!/usr/bin/env python3
"""Create or update a prompt agent and give it MCP tools.

By default, the service's MCP tool is attached directly to the agent. With
--toolbox-name, the agent gets a toolbox (from create_toolbox.py) instead,
which exposes every tool in that toolbox. Either way, the tools use the Foundry
OAuth connections from the Bicep deployment, so each user signs in to each
service once and every call runs as that user.

Examples:

    python scripts/deploy_agent.py --resource-group rg-mcp-agent --service github --github-org my-org
    python scripts/deploy_agent.py --resource-group rg-mcp-agent --service zoominfo
    python scripts/deploy_agent.py --resource-group rg-mcp-agent --service zoominfo --toolbox-name mcp-tools
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

from common import SERVICES, az, deployment_outputs, require_service, with_retry
from create_toolbox import project_id_from, toolbox_connection_id, toolbox_url

PLACEHOLDER = re.compile(r"\$\{([A-Z0-9_]+)\}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--resource-group", required=True)
    parser.add_argument("--service", required=True, choices=sorted(SERVICES))
    parser.add_argument("--deployment-name", default="main")
    parser.add_argument("--subscription", help="Defaults to the active Azure CLI subscription")
    parser.add_argument(
        "--github-org",
        help="GitHub only: the organization the agent uses when the user doesn't name one",
    )
    parser.add_argument("--agent-name", help="Overrides the name in the definition file")
    parser.add_argument(
        "--toolbox-name",
        help=(
            "Attach this toolbox (from create_toolbox.py) instead of the definition's "
            "direct tool. The agent gets every tool in the toolbox."
        ),
    )
    parser.add_argument(
        "--definition",
        type=Path,
        help="Overrides the agent definition file (default: agent/<service>-agent.yaml)",
    )
    args = parser.parse_args()
    if args.service == "github" and not args.github_org:
        parser.error("--github-org is required for --service github")
    return args


def render(definition_path: Path, values: dict[str, str]) -> dict:
    text = definition_path.read_text(encoding="utf-8")
    missing = sorted({name for name in PLACEHOLDER.findall(text) if not values.get(name)})
    if missing:
        raise ValueError(f"No value for placeholders in {definition_path.name}: {', '.join(missing)}")
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


def toolbox_tool(outputs: dict, service: str, toolbox_name: str) -> MCPTool:
    """One MCP tool that exposes every tool in the toolbox."""
    connection_id = toolbox_connection_id(project_id_from(outputs, [service]), toolbox_name)
    try:
        az("rest", "--method", "get", "--url",
           f"https://management.azure.com{connection_id}?api-version=2025-06-01")
    except RuntimeError as exc:
        raise RuntimeError(
            f"Toolbox connection '{toolbox_name}-user' wasn't found. Run "
            f"scripts/create_toolbox.py --toolbox-name {toolbox_name} first."
        ) from exc
    return MCPTool(
        server_label=re.sub(r"[^A-Za-z0-9_]", "_", toolbox_name),
        server_url=toolbox_url(outputs["projectEndpoint"], toolbox_name),
        project_connection_id=connection_id,
        require_approval="never",
    )


def main() -> None:
    args = parse_args()
    outputs = deployment_outputs(args.resource_group, args.deployment_name, args.subscription)
    settings = require_service(args.service, outputs)

    values = {"MODEL_DEPLOYMENT_NAME": outputs["modelDeploymentName"]}
    values.update({name: outputs[output] for name, output in settings["outputs"].items()})
    if args.github_org:
        values["GITHUB_ORG"] = args.github_org

    definition = render(args.definition or settings["definition"], values)
    agent_name = args.agent_name or definition["name"]
    if args.toolbox_name:
        tools = [toolbox_tool(outputs, args.service, args.toolbox_name)]
    else:
        tools = build_tools(definition.get("tools", []))

    client = AIProjectClient(
        endpoint=outputs["projectEndpoint"], credential=AzureCliCredential()
    )
    agent = with_retry(
        lambda: client.agents.create_version(
            agent_name=agent_name,
            definition=PromptAgentDefinition(
                model=definition["model"],
                instructions=definition["instructions"],
                tools=tools,
            ),
        )
    )
    attached = f"toolbox '{args.toolbox_name}'" if args.toolbox_name else "its MCP tool directly"
    print(f"Deployed agent '{agent.name}' version {agent.version} with {attached}.")
    print(f"Project endpoint: {outputs['projectEndpoint']}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 -- concise CLI error
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
