"""Shared helpers for the deployment scripts."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from typing import Any, Callable, TypeVar

from azure.core.exceptions import ServiceRequestError, ServiceResponseError
from openai import APIConnectionError

T = TypeVar("T")
TRANSIENT_ERRORS = (ServiceRequestError, ServiceResponseError, APIConnectionError)


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
) -> dict[str, str]:
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
