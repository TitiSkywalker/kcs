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

## MCP server

Start an MCP server to let coding agents run commands, read files, and write
files inside your containers.

**CLI (standalone process):**

```bash
kcs -P <api-port> mcp --container <name> --mcp-port <mcp-port>
```

**API (in-process):**

```bash
curl -X POST localhost:<api-port>/api/v1/mcp/start \
  -H 'Content-Type: application/json' \
  -d '{"container": "<name>", "port": <mcp-port>}'
```

**Connect Claude Code** (`~/.claude/claude.json`):

```json
"mcpServers": {
  "kcs": { "url": "http://127.0.0.1:<mcp-port>/sse" }
}
```

Four tools exposed: `container_exec`, `container_read`, `container_write`,
`container_list`. When `--container` is set, the container parameter is hidden from the agent — every call targets that container automatically.  Without it, the agent has to pick a container per call manually.

## Tests

```bash
python tests/runner.py          # integration suite
python tests/performance.py     # throughput + latency benchmarks
```
