<p align="center"><img src="src/kcs/static/icon.svg" width="140" alt="kcs"></p>

Container controller made simpler than k3s — declarative cluster config,
dashboard, REST API, and Claude Code shell integration.

## Setup

Requires **Python ≥ 3.12**, **k3s**, and **kubectl**.

```bash
pip install -e ".[dev]"
```

Optional: `docker` for image builds, `sshpass` for worker password auth.

## Quick start

```bash
kcs serve --port 8000 --config cluster.toml
```

```toml
# cluster.toml
api_key = "<secret>"           # required
nfs_path = "/srv/nfs/k3s"

[[workers]]
host = "<ip>"
user = "root"
password = "<ssh-password>"    # optional — uses pipe, never environ
```

Open `http://localhost:8000` for the dashboard, `http://localhost:8000/docs` for the API docs.

On startup, kcs applies the config: joins workers, deploys the NFS provisioner, prunes stale nodes. Already-joined workers are skipped. No manual steps.

## Dashboard

Topology view of the entire cluster — server, workers, containers, hardware usage bars (CPU / memory / GPU), node health, and NFS status. Create, stop, start, scale, and delete containers from the UI. Shell proxy management with one-click start/stop and copy-to-clipboard.

## CLI

```bash
kcs build -t myapp:v1 .           # build image → cluster registry
kcs exec web -- ls -la            # run command in container
kcs ssh web                       # interactive shell
kcs -P 8000 shell-proxy -c web    # start shell proxy via API
```

## Shell proxy

Forwards Claude Code's Bash commands into a container over a Unix domain socket. Working directory and env are preserved across calls.

```bash
kcs -P 8000 shell-proxy -c web
CLAUDE_CODE_SHELL=~/.local/bin/kcs-bash-web claude
```

A self-contained wrapper script is auto-created at `~/.local/bin/kcs-bash-<container>`. Sessions are isolated:

```bash
kcs -P 8000 shell-proxy -c web -s alice   # kcs-bash-web-alice
kcs -P 8000 shell-proxy -c web -s bob     # kcs-bash-web-bob
```

## Security

| area | approach |
|------|----------|
| API auth | Bearer token (`api_key` in config or `KCS_API_KEY` env). Dashboard prompts on 401. |
| Network | Default bind `127.0.0.1`; `--host 0.0.0.0` to expose. |
| TLS | `--ssl-certfile`/`--ssl-keyfile` (or `KCS_SSL_CERT`/`KCS_SSL_KEY`). |
| Rate limit | 120 req/min via slowapi. |
| Shell proxy | Unix socket `~/.kcs/proxy-*.sock`, `0600` — kernel-enforced owner-only access. |
| SSH | Password via pipe fd (`sshpass -d`), never in environment. Cleared after each call. |
| NFS | `root_squash`, `755`, export restricted to worker hosts. |
| Input | Container names RFC 1123-validated. Command args `shlex.join`-escaped. |
| Secrets | Sudo password wiped from memory after startup. |

## Tests

```bash
pytest tests/ -v                # 29 integration tests
python tests/performance.py     # throughput + latency benchmarks
```
