"""kcs CLI — HTTP client for kcs server."""

from __future__ import annotations

import os
import sys

import click
import requests
from rich.console import Console

from kcs import __version__

console = Console()


def _api(path: str, method: str = "GET", json_data=None, params=None, stream=False):
    ctx = click.get_current_context()
    port = ctx.obj.get("port", 8000)
    url = f"http://localhost:{port}/api/v1{path}"
    try:
        r = requests.request(
            method, url, json=json_data, params=params, stream=stream, timeout=120
        )
    except requests.ConnectionError:
        raise click.ClickException(
            f"Cannot connect to http://localhost:{port} — server running? (kcs serve)"
        )
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail", r.text[:200])
        except Exception:
            detail = r.text[:200]
        raise click.ClickException(f"Error {r.status_code}: {detail}")
    if stream:
        return r
    return r.json()


# ══════════════════════════════════════════════════════════════════════════════


@click.group()
@click.version_option(version=__version__, prog_name="kcs")
@click.option(
    "-P", "--port", envvar="KCS_PORT", default=8000, type=int, help="Server port"
)
@click.pass_context
def main(ctx: click.Context, port: int) -> None:
    """kcs — container controller made simpler than k3s."""
    ctx.ensure_object(dict)
    ctx.obj["port"] = port


# ══════════════════════════════════════════════════════════════════════════════
# kcs serve
# ══════════════════════════════════════════════════════════════════════════════


@main.command()
@click.option("--host", envvar="KCS_HOST", default="0.0.0.0")
@click.option("--port", envvar="KCS_PORT", default=8000, type=int)
@click.option("-c", "--config", default=None, help="Cluster config file (.toml/.yaml)")
@click.option("--log-file", default=None)
@click.option("-v", "--verbose", is_flag=True, help="Enable DEBUG-level logging")
@click.option("--no-nfs", is_flag=True, help="Skip NFS setup even when --config is provided")
def serve(host: str, port: int, config: str | None, log_file: str | None,
          verbose: bool, no_nfs: bool) -> None:
    """Start API server + Dashboard."""
    from kcs.server.main import main as server_main

    sys.argv = ["kcs-server", "--host", host, "--port", str(port)]
    if config:
        sys.argv.extend(["--config", config])
    if log_file:
        sys.argv.extend(["--log-file", log_file])
    if verbose:
        sys.argv.append("--verbose")
    if no_nfs:
        sys.argv.append("--no-nfs")
    server_main()


# ══════════════════════════════════════════════════════════════════════════════
# kcs build
# ══════════════════════════════════════════════════════════════════════════════


@main.command()
@click.argument("path", default=".")
@click.option("-t", "--tag", required=True, help="Image name:tag")
@click.option("--no-push", is_flag=True, help="Build only, do not push")
def build(path: str, tag: str, no_push: bool) -> None:
    """Build Docker image and push to cluster registry.

    kcs build -t myapp:v1 .
    """
    data = _api(
        "/build",
        method="POST",
        json_data={"tag": tag, "path": path, "no_push": no_push},
    )
    console.print(f"[green]✓[/] {data['message']}")


# ══════════════════════════════════════════════════════════════════════════════
# kcs shell-proxy
# ══════════════════════════════════════════════════════════════════════════════


@main.command("shell-proxy")
@click.option(
    "--container", "-c", required=True, help="Target container for all commands"
)
@click.option("--host", default="127.0.0.1", help="Proxy listen address")
@click.option("--port", default=9876, type=int, help="Proxy listen port")
@click.option("--session", "-s", default="", help="Session label (for multiple proxies per container)")
@click.option("--verbose", "-v", is_flag=True, help="Log every command to stderr")
@click.pass_context
def shell_proxy(
    ctx: click.Context, container: str, host: str, port: int, session: str, verbose: bool
) -> None:
    """Start a shell proxy server for CLAUDE_CODE_SHELL integration.

    Auto-creates wrapper at ~/.local/bin/kcs-bash-<container>[-<session>].

    \b
    1. Start the proxy:
         kcs -P 8888 shell-proxy --container web -v

    \b
    2. Use with Claude Code:
         CLAUDE_CODE_SHELL=~/.local/bin/kcs-bash-web claude

    \b
    Multiple sessions per container:
         kcs -P 8888 shell-proxy -c web -s alice
         kcs -P 8888 shell-proxy -c web -s bob --port 9877
    """
    from kcs.shell_proxy import run_server

    api_port = ctx.obj.get("port", 8000)
    run_server(container, host=host, port=port, verbose=verbose, session=session,
               api_port=api_port)


# ══════════════════════════════════════════════════════════════════════════════
# kcs exec
# ══════════════════════════════════════════════════════════════════════════════


@main.command(context_settings={"ignore_unknown_options": True})
@click.argument("name")
@click.argument("command", nargs=-1, type=str)
@click.option("--pod", default=None, type=int, help="Pod ordinal")
def exec_cmd(name: str, command: tuple[str, ...], pod: int | None) -> None:
    """Run a command inside a container.  kcs exec web -- ls -la"""
    if not command:
        raise click.ClickException(
            "No command specified.  Usage: kcs exec <name> -- <command...>"
        )
    try:
        result = _api(
            f"/containers/{name}/exec",
            method="POST",
            json_data={"command": list(command)},
            params={"pod": pod} if pod is not None else None,
        )
    except click.ClickException as e:
        # Exec errors carry the output as detail — print it and exit
        msg = str(e)
        # Strip the "Error 500: " prefix if present
        if msg.startswith("Error "):
            msg = msg.split(":", 1)[-1].strip()
        console.print(msg)
        sys.exit(1)
    output = result.get("output", "")
    if output and output != "(empty)":
        console.print(output)


# ══════════════════════════════════════════════════════════════════════════════
# kcs ssh
# ══════════════════════════════════════════════════════════════════════════════


@main.command()
@click.argument("name")
@click.option("--pod", default=None, type=int, help="Pod ordinal")
def ssh(name: str, pod: int | None) -> None:
    """Open a shell inside a container.  kcs ssh web"""
    pods_data = _api(f"/containers/{name}/pods")
    pods = pods_data.get("pods", [])
    if not pods:
        raise click.ClickException(f"No pods found for '{name}'")

    idx = pod if pod is not None else 0
    if idx >= len(pods):
        raise click.ClickException(f"Pod {idx} out of range (0-{len(pods) - 1})")

    kubeconfig = os.environ.get("KUBECONFIG") or os.path.expanduser("~/.kcs/k3s.yaml")
    if not os.path.exists(kubeconfig):
        kubeconfig = "/etc/rancher/k3s/k3s.yaml"

    env = os.environ.copy()
    env["KUBECONFIG"] = kubeconfig
    os.execvpe(
        "kubectl", ["kubectl", "exec", "-it", pods[idx]["name"], "--", "/bin/sh"], env
    )


if __name__ == "__main__":
    main()
