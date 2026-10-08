#!/usr/bin/env python3
"""Smoke-test an agent as the signed-in Azure CLI user.

Tool calls run as that user. If the user hasn't signed in to the service
through the agent yet, the script prints the sign-in link and exits with
code 2. Sign in, then run the script again.

Examples:

    python scripts/smoke_test.py --resource-group rg-mcp-agent --service github --github-org my-org
    python scripts/smoke_test.py --resource-group rg-mcp-agent --service zoominfo
"""

from __future__ import annotations

import argparse
import sys

from azure.ai.projects import AIProjectClient
from azure.identity import AzureCliCredential

from common import SERVICES, deployment_outputs, require_service, with_retry

# ZoomInfo's Lookup tool is free; enrichment and research tools use credits.
DEFAULT_PROMPTS = {
    "github": "Who am I on GitHub? Then list the repositories in the {org} organization.",
    "zoominfo": "Use the ZoomInfo lookup tool to list the valid management level values.",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--resource-group", required=True)
    parser.add_argument("--service", required=True, choices=sorted(SERVICES))
    parser.add_argument("--deployment-name", default="main")
    parser.add_argument("--subscription", help="Defaults to the active Azure CLI subscription")
    parser.add_argument("--github-org", help="GitHub only: organization to list")
    parser.add_argument("--agent-name", help="Defaults to the service's agent name")
    parser.add_argument("--prompt", help="Overrides the default test prompt")
    args = parser.parse_args()
    if args.service == "github" and not (args.github_org or args.prompt):
        parser.error("--github-org (or --prompt) is required for --service github")
    return args


def main() -> int:
    args = parse_args()
    outputs = deployment_outputs(args.resource_group, args.deployment_name, args.subscription)
    settings = require_service(args.service, outputs)
    prompt = args.prompt or DEFAULT_PROMPTS[args.service].format(org=args.github_org)
    agent_name = args.agent_name or settings["agent_name"]

    client = AIProjectClient(
        endpoint=outputs["projectEndpoint"], credential=AzureCliCredential()
    )
    openai = client.get_openai_client()
    response = with_retry(
        lambda: openai.responses.create(
            input=prompt,
            extra_body={"agent_reference": {"name": agent_name, "type": "agent_reference"}},
        )
    )

    for item in response.output:
        if item.type == "oauth_consent_request":
            print(f"Sign in to {settings['label']} to continue. Open this link:")
            print(item.consent_link)
            print("Then run this script again.")
            return 2
        if item.type == "mcp_approval_request":
            print("The agent asked for tool approval. Set require_approval to 'never' for this tool.")
            return 1

    calls = [item for item in response.output if item.type == "mcp_call"]
    for call in calls:
        status = "error" if getattr(call, "error", None) else "ok"
        print(f"tool {call.name}: {status}")
    print()
    print(response.output_text)

    if not calls:
        print(f"FAIL: the agent didn't call any {settings['label']} tools.", file=sys.stderr)
        return 1
    if any(getattr(call, "error", None) for call in calls):
        print("FAIL: at least one tool call failed.", file=sys.stderr)
        return 1
    print("\nPASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
