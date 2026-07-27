<p align="center"><img src="src/kcs/static/icon.svg" width="140" alt="kcs"></p>

Container controller made simpler than k3s — declarative cluster management,
REST API, dashboard, and native coding-agent integration.

## Requirements

- **k3s** — lightweight Kubernetes (server and all workers)
- **kubectl** — cluster access (bundled with k3s)
- **Python ≥ 3.12**

Optional, depending on features used:

| dependency | needed for |
|---|---|
| `docker` | `kcs build` — image builds and push to registry |
| `sshpass` | worker join with password auth (skip if using SSH keys) |

## Install

```bash
pip install -e ".[dev]"
```

## Cluster management

Define your entire cluster in a single config file. kcs applies it on startup — joins workers, sets up NFS shared storage, and prunes stale nodes.

```bash
kcs serve --port <api-port> --config cluster.toml
```

```toml
# cluster.toml
nfs_path = "/srv/nfs/k3s"

[[workers]]
host = "<ip>"
user = "root"
password = "<ssh-password>"
```

Workers already joined are skipped. Workers removed from the config are pruned. The NFS provisioner is deployed automatically so PVCs work across all nodes.

## HTTP API & Dashboard

`kcs serve --config cluster.toml` starts the API, dashboard, and cluster automation on one port. Dashboard at `http://localhost:<api-port>`, API docs at `http://localhost:<api-port>/docs`.

- **Dashboard** — topology view showing server, workers, containers, hardware usage (CPU / memory / GPU progress bars), node health, and NFS status. Create, stop, start, and delete containers from the UI.
- **API** — full CRUD for containers, image builds, cluster status. OpenAPI docs at `/docs`.  Hardware declarations (`gpus`, `cpu`, `memory`) are passed through as Kubernetes resource requests with exclusive allocation.

```bash
# Build an image and push to the cluster registry
kcs build -t <image>:<tag> .

# Run a command inside a container
kcs exec <container> -- <command...>

# Open an interactive shell
kcs ssh <container>
```

## Coding-agent integration

`kcs shell-proxy` forwards Claude Code's Bash tool commands into a container
via a persistent PTY session.  Claude Code's built-in Bash tool replaces your local shell transparently — every command runs inside the target container.

```bash
# Start the proxy (leave this running)
kcs shell-proxy --container <name> -v

# In another terminal, launch Claude Code:
CLAUDE_CODE_SHELL=/home/you/.local/bin/kcs-bash-<name> claude
```

The proxy auto-creates the wrapper script at `~/.local/bin/kcs-bash-<name>`.
`CLAUDE_CODE_SHELL` tells Claude Code to use that script instead of `/bin/bash`. The script then forwards commands over TCP to the proxy.

`kcs` also supports multiple containers, each on its own port:
```bash
kcs shell-proxy -c container1 --port 9876
kcs shell-proxy -c container2 --port 9877
```

## Tests

```bash
pytest tests/ -v                # integration suite
python tests/performance.py     # throughput + latency benchmarks
```
