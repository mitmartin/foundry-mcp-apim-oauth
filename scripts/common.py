"""Shared helpers for the deployment scripts."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, TypeVar

from azure.core.exceptions import ServiceRequestError, ServiceResponseError
from openai import APIConnectionError

T = TypeVar("T")
TRANSIENT_ERRORS = (ServiceRequestError, ServiceResponseError, APIConnectionError)

REPO_ROOT = Path(__file__).resolve().parent.parent

# Per-service settings shared by deploy_agent.py and smoke_test.py.
SERVICES: dict[str, dict[str, Any]] = {
    "github": {
        "label": "GitHub",
        "enable_parameter": "enableGitHub",
        "definition": REPO_ROOT / "agent" / "github-agent.yaml",
        "agent_name": "github-mcp-agent",
        "registered_output": "githubRegistered",
        "outputs": {
            "GITHUB_MCP_URL": "githubMcpUrl",
            "GITHUB_CONNECTION_ID": "githubConnectionId",
        },
    },
    "zoominfo": {
        "label": "ZoomInfo",
        "enable_parameter": "enableZoomInfo",
        "definition": REPO_ROOT / "agent" / "zoominfo-agent.yaml",
        "agent_name": "zoominfo-research-agent",
        "registered_output": "zoominfoRegistered",
        "outputs": {
            "ZOOMINFO_MCP_URL": "zoominfoMcpUrl",
            "ZOOMINFO_CONNECTION_ID": "zoominfoConnectionId",
        },
    },
}


def az(*args: str) -> Any:
    """Run an Azure CLI command and return its JSON output."""
    executable = shutil.which("az")
    if not executable:
        raise RuntimeError("Azure CLI (az) isn't installed or isn't on PATH.")
    completed = subprocess.run(
        [executable, *args, "--output", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "Azure CLI command failed.")
    return json.loads(completed.stdout or "null")


def deployment_outputs(
    resource_group: str, deployment: str, subscription: str | None
) -> dict[str, Any]:
    """Return the outputs of a resource group deployment as a flat dict."""
    args = [
        "deployment",
        "group",
        "show",
        "--resource-group",
        resource_group,
        "--name",
        deployment,
        "--query",
        "properties.outputs",
    ]
    if subscription:
        args += ["--subscription", subscription]
    outputs = az(*args) or {}
    if not outputs:
        raise RuntimeError(
            f"Deployment '{deployment}' in '{resource_group}' has no outputs."
        )
    return {name: value["value"] for name, value in outputs.items()}


def require_service(service: str, outputs: dict[str, Any]) -> dict[str, Any]:
    """Return the service settings, or explain how to enable the service."""
    settings = SERVICES[service]
    if not all(outputs.get(name) for name in settings["outputs"].values()):
        raise RuntimeError(
            f"{settings['label']} isn't deployed. Redeploy the infrastructure with "
            f"{settings['enable_parameter']}=true."
        )
    if not outputs.get(settings["registered_output"]):
        print(
            f"WARNING: the {settings['label']} connection still has placeholder "
            "credentials, so users can't sign in yet. Redeploy the infrastructure "
            "with the app's client ID and secret."
        )
    return settings


def with_retry(fn: Callable[[], T], attempts: int = 5, delay: int = 10) -> T:
    """Retry transient network failures; surface every other error."""
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except TRANSIENT_ERRORS:
            if attempt == attempts:
                raise
            time.sleep(delay)
    raise AssertionError("unreachable")
