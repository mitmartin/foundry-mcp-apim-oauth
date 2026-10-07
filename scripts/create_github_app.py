#!/usr/bin/env python3
"""Create a read-only GitHub App for a GitHub organization (manifest flow).

The script starts a local web page that sends a prepared app manifest to
GitHub. You review and confirm the app in GitHub, and the script saves the
app's client ID and client secret to a file outside the repository.

Example:

    python scripts/create_github_app.py --org my-org --app-name my-org-foundry-mcp

By default, the script prints URLs for you to open. Use --open-browser to open
them automatically. Open them in the browser where you're signed in to GitHub
as an owner of the organization.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import secrets
import threading
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

READ_ONLY_PERMISSIONS = {
    "actions": "read",
    "contents": "read",
    "issues": "read",
    "metadata": "read",
    "pull_requests": "read",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--org", required=True, help="GitHub organization that owns the app")
    parser.add_argument(
        "--app-name",
        required=True,
        help="GitHub App name. Must be unique across GitHub.",
    )
    parser.add_argument("--homepage-url", help="Defaults to https://github.com/<org>")
    parser.add_argument(
        "--output",
        type=Path,
        help="Credentials file. Defaults to ~/.foundry-mcp/<app-name>.json",
    )
    parser.add_argument("--open-browser", action="store_true")
    parser.add_argument("--timeout", type=int, default=900, help="Seconds to wait")
    return parser.parse_args()


def show(url: str, label: str, open_browser: bool) -> None:
    print(f"\n{label}\n  {url}\n", flush=True)
    if open_browser:
        webbrowser.open(url)


def save_credentials(path: Path, app: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "app_id": app["id"],
        "slug": app["slug"],
        "client_id": app["client_id"],
        "client_secret": app["client_secret"],
        "html_url": app["html_url"],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if os.name != "nt":
        path.chmod(0o600)


def main() -> None:
    args = parse_args()
    output = args.output or Path.home() / ".foundry-mcp" / f"{args.app_name}.json"
    state = secrets.token_urlsafe(32)
    created = threading.Event()
    installed = threading.Event()
    app: dict = {}

    server = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    local = f"http://127.0.0.1:{server.server_address[1]}"
    manifest = {
        "name": args.app_name,
        "url": args.homepage_url or f"https://github.com/{args.org}",
        "description": "Read-only GitHub access for Microsoft Foundry agents. Each call runs as the signed-in user.",
        "redirect_url": f"{local}/created",
        "setup_url": f"{local}/installed",
        "public": False,
        "request_oauth_on_install": False,
        "setup_on_update": False,
        "default_permissions": READ_ONLY_PERMISSIONS,
        "default_events": [],
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_: object) -> None:
            return

        def reply(self, status: int, body: str) -> None:
            data = f"<!doctype html><html><body>{body}</body></html>".encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802
            url = urllib.parse.urlparse(self.path)
            query = urllib.parse.parse_qs(url.query)

            if url.path == "/":
                action = (
                    f"https://github.com/organizations/{urllib.parse.quote(args.org)}"
                    f"/settings/apps/new?state={state}"
                )
                self.reply(
                    200,
                    f'<p>Sending the app manifest to GitHub...</p>'
                    f'<form id="f" action="{html.escape(action)}" method="post">'
                    f'<input type="hidden" name="manifest" '
                    f'value="{html.escape(json.dumps(manifest), quote=True)}">'
                    f'<button type="submit">Continue to GitHub</button></form>'
                    f'<script>document.getElementById("f").submit();</script>',
                )
                return

            if url.path == "/created":
                if query.get("state", [""])[0] != state or not query.get("code"):
                    self.reply(400, "<p>Invalid response from GitHub. Close this tab and try again.</p>")
                    return
                request = urllib.request.Request(
                    f"https://api.github.com/app-manifests/{query['code'][0]}/conversions",
                    method="POST",
                    headers={
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                        "User-Agent": "foundry-mcp-setup",
                    },
                )
                with urllib.request.urlopen(request, timeout=60) as response:
                    app.update(json.load(response))
                save_credentials(output, app)
                created.set()
                self.reply(200, "<p>GitHub App created. Return to the terminal for the next step.</p>")
                return

            if url.path == "/installed":
                installed.set()
                self.reply(200, "<p>GitHub App installed. You can close this tab.</p>")
                return

            self.reply(404, "<p>Not found.</p>")

    server.RequestHandlerClass = Handler
    threading.Thread(target=server.serve_forever, daemon=True).start()

    print(f"Creating GitHub App '{args.app_name}' in organization '{args.org}'.")
    print("Use a browser where you're signed in to GitHub as an owner of that organization.")
    show(f"{local}/", "Step 1. Open this page, review the app, and select Create GitHub App:", args.open_browser)

    if not created.wait(args.timeout):
        server.shutdown()
        raise SystemExit("Timed out waiting for GitHub App creation.")

    print(f"Created '{app['slug']}'. Credentials saved to {output}")
    print("Keep that file private. Never commit it.")
    show(
        f"https://github.com/apps/{app['slug']}/installations/new",
        f"Step 2. Install the app on '{args.org}' and choose the repositories the agent may read:",
        args.open_browser,
    )

    if installed.wait(args.timeout):
        print("Installation recorded.")
    else:
        print("No installation callback received. Confirm the installation in GitHub.")
    server.shutdown()

    print("\nNext:")
    print(f"  * Deploy infra with githubAppClientId={app['client_id']} and the client secret from {output}.")
    print("  * Then add the githubOAuthRedirectUrl deployment output as a callback URL at:")
    print(f"    https://github.com/organizations/{args.org}/settings/apps/{app['slug']}")


if __name__ == "__main__":
    main()
