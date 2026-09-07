# Hostinger VPS — server build-out (Dokploy)

How the current server was built, and how to rebuild it. For day-to-day
deploys see `GO_LIVE_RUNBOOK.md`.

> Supersedes the earlier systemd + nginx + certbot approach. `provision.sh`,
> `chatbot.service`, and `chatbot-nginx.conf` are legacy and unused.

## Server

Hostinger KVM 2 — 2 vCPU, 8 GB RAM, 100 GB NVMe, Mumbai.
`200.234.45.226` / `srv1962056.hstgr.cloud`, Ubuntu 26.04.1 LTS (`resolute`), root.

## ⚠️ Dokploy's installer fails on Ubuntu 26.04 — install Docker first

`install.sh` pins Docker **28.5.0**, which was never published for `resolute`;
that repo only carries 29.x. The installer dies with:

```
ERROR: '28.5.0' not found amongst apt-cache madison results
...
docker: not found
Error: Failed to initialize Docker Swarm
```

It also leaves the docker packages on apt hold. Install Docker manually first —
the installer skips its own Docker step when `command -v docker` succeeds:

```bash
apt-mark unhold docker-ce docker-ce-cli docker-ce-rootless-extras
apt-get install -y docker-ce docker-ce-cli containerd.io \
                   docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
```

## Build order

```bash
# 1. Docker DNS — write BEFORE Docker's first start, or in-container
#    builds fail to resolve hostnames on this provider.
mkdir -p /etc/docker
echo '{"dns": ["1.1.1.1", "8.8.8.8"]}' > /etc/docker/daemon.json

# 2. Firewall — allow 22 BEFORE enabling, or you lock yourself out.
ufw allow 22/tcp && ufw allow 80/tcp && ufw allow 443/tcp && ufw allow 3000/tcp
ufw --force enable

# 3. Docker (see above), then Dokploy
curl -sSL https://dokploy.com/install.sh | sh
```

Then claim the admin account at `http://<IP>:3000` **immediately** — the first
visitor to reach it owns the instance, and the port is world-reachable.

## Application configuration

| Setting | Value |
|---|---|
| Source | Git (public URL — no GitHub App, no deploy key) |
| Repo / branch | `https://github.com/Harkeerat-ai/chatbotllm.git` / `main` |
| Build type | Nixpacks (reads `Procfile` + `runtime.txt` → Python 3.12) |
| Port | 3000 (`Procfile` binds `$PORT`, so `PORT=3000` must be set) |
| Volume | `kalp-chatbot-data` → `/app/data` |
| Domain | `chat.kalp-shop.in`, HTTPS, Let's Encrypt |

Nixpacks builds Python **inside the container** from `runtime.txt`. This is why
Docker was chosen over a native venv: the host runs Python 3.14 and 26.04 has no
`python3.12` package, so `chromadb`/`torch`/`pymupdf` wheels would not resolve.

The first build takes ~10 minutes — it pulls the full PyTorch stack for
in-process embeddings. Later builds reuse cached layers.

## Embeddings run locally, on purpose

`USE_LOCAL_EMBEDDINGS=true` runs `all-MiniLM-L6-v2` in-process. The alternative
(`HF_API_TOKEN`) adds a network round trip per query plus cold-start stalls on
an idle endpoint. OpenRouter has no embeddings endpoint and cannot substitute.

Set `HF_HOME=/app/data/hf-cache` so weights land on the volume. The app loads a
**second** model — a `ms-marco-MiniLM-L6-v2` reranker — so without this, both
re-download on every container start and the first query after each deploy hangs.

## Access

SSH key at `~/.ssh/kalp_vps`, aliased `kalpvps` in `~/.ssh/config`.

## Known-open items

- Port 3000 is open to the internet. Restrict the ufw rule to a known IP once
  UI access is no longer needed.
- Backups: Hostinger takes weekly disk snapshots. There is no separate
  volume-level backup of `kalp-chatbot-data`.
