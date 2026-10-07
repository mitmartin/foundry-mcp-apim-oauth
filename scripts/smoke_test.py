#!/usr/bin/env python3
"""Smoke-test the agent as the signed-in Azure CLI user.

GitHub calls run as that user. If the user hasn't signed in to GitHub through
the agent yet, the script prints the sign-in link and exits with code 2.
Sign in, then run the script again.

Example:

    python scripts/smoke_test.py --resource-group rg-mcp-agent --github-org my-org
"""

from __future__ import annotations

import argparse
import sys

from azure.ai.projects import AIProjectClient
from azure.identity import AzureCliCredential

from common import deployment_outputs, with_retry


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--resource-group", required=True)
    parser.add_argument("--deployment-name", default="main")
    parser.add_argument("--subscription", help="Defaults to the active Azure CLI subscription")
    parser.add_argument("--github-org", required=True)
    parser.add_argument("--agent-name", default="github-mcp-agent")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    outputs = deployment_outputs(args.resource_group, args.deployment_name, args.subscription)
    client = AIProjectClient(
        endpoint=outputs["projectEndpoint"], credential=AzureCliCredential()
    )
    openai = client.get_openai_client()
    agent = {"agent_reference": {"name": args.agent_name, "type": "agent_reference"}}

    response = with_retry(
        lambda: openai.responses.create(
            input=(
                "Who am I on GitHub? Then list the repositories in the "
                f"{args.github_org} organization."
            ),
            extra_body=agent,
        )
    )

    for item in response.output:
        if item.type == "oauth_consent_request":
            print("Sign in to GitHub to continue. Open this link:")
            print(item.consent_link)
            print("Then run this script again.")
            return 2
        if item.type == "mcp_approval_request":
            print("The agent asked for tool approval. Set require_approval to 'never' for read-only tools.")
            return 1

    calls = [item for item in response.output if item.type == "mcp_call"]
    for call in calls:
        status = "error" if getattr(call, "error", None) else "ok"
        print(f"tool {call.name}: {status}")
    print()
    print(response.output_text)

    if not calls:
        print("FAIL: the agent didn't call any GitHub tools.", file=sys.stderr)
        return 1
    if any(getattr(call, "error", None) for call in calls):
        print("FAIL: at least one GitHub tool call failed.", file=sys.stderr)
        return 1
    print("\nPASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
