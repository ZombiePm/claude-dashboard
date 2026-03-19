# Claude Dashboard

Web dashboard for [Claude Code](https://claude.ai/claude-code) — browse memory files and session history in a browser.

![Python](https://img.shields.io/badge/python-3.10+-blue) ![Dependencies](https://img.shields.io/badge/dependencies-0-green) ![Docker](https://img.shields.io/badge/docker-ready-blue)

## Features

- **Memory viewer** — sidebar grouped by type (user, feedback, project, reference), rendered markdown, raw view, full-text search
- **Sessions viewer** — sortable table of all sessions, full-text search across all messages (not just first/last), click-to-copy resume commands
- **Session drawer** — click any row to open a side panel with the full conversation log, search term highlighting
- **Auth** — simple login/password with cookie sessions
- **Zero dependencies** — pure Python stdlib, single file, no pip install needed

## Quick Start

### Docker Compose

```bash
git clone https://github.com/youruser/claude-dashboard.git
cd claude-dashboard

# Set credentials
export AUTH_USER=admin
export AUTH_PASS=your-secure-password

docker compose up -d
```

Open `http://localhost:8080`

### Docker in existing compose

Add to your `docker-compose.yml`:

```yaml
  claude-dashboard:
    build: /path/to/claude-dashboard
    container_name: claude-dashboard
    restart: unless-stopped
    volumes:
      - ~/.claude-code/memory:/data/memory:ro
      - ~/.claude/history.jsonl:/data/history.jsonl:ro
    environment:
      BIND: "0.0.0.0"
      PORT: "80"
      USE_SSL: "0"
      MEMORY_DIR: /data/memory
      HISTORY_FILE: /data/history.jsonl
      AUTH_USER: admin
      AUTH_PASS: your-secure-password
```

### Behind reverse proxy (Nginx Proxy Manager, Traefik, etc.)

1. Add the container to the same Docker network as your proxy
2. Create proxy host: `dashboard.example.com` → `claude-dashboard:80` (http)
3. Enable SSL on the proxy side

### Standalone (no Docker)

```bash
export AUTH_USER=admin
export AUTH_PASS=your-secure-password
export BIND=0.0.0.0
export PORT=8080
export USE_SSL=0
python3 server.py
```

### With SSL

```bash
# Generate self-signed cert
openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem \
  -days 365 -nodes -subj '/CN=localhost'

export USE_SSL=1
export CERT_FILE=cert.pem
export KEY_FILE=key.pem
python3 server.py
```

### Systemd service

```ini
[Unit]
Description=Claude Dashboard
After=network.target

[Service]
Type=simple
Environment=BIND=0.0.0.0
Environment=PORT=8080
Environment=USE_SSL=0
Environment=AUTH_USER=admin
Environment=AUTH_PASS=your-secure-password
Environment=MEMORY_DIR=/path/to/memory
Environment=HISTORY_FILE=/path/to/history.jsonl
ExecStart=/usr/bin/python3 /opt/claude-dashboard/server.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

## Configuration

All settings via environment variables:

| Variable | Default | Description |
|---|---|---|
| `BIND` | `0.0.0.0` | Listen address |
| `PORT` | `8080` | Listen port |
| `USE_SSL` | `1` | `1` = HTTPS, `0` = HTTP |
| `CERT_FILE` | `cert.pem` | SSL certificate (when `USE_SSL=1`) |
| `KEY_FILE` | `key.pem` | SSL private key (when `USE_SSL=1`) |
| `MEMORY_DIR` | `/root/MEMORY` | Claude Code memory directory |
| `HISTORY_FILE` | `/root/.claude/history.jsonl` | Claude Code session history |
| `AUTH_USER` | `admin` | Login username |
| `AUTH_PASS` | `changeme` | Login password |
| `NORM_PATH_MAP` | _(empty)_ | Path normalization rules (see below) |

### Path normalization

Sessions store project paths from the machine where Claude Code ran (often Windows paths). The dashboard normalizes them for the `cd` command. Configure with `NORM_PATH_MAP`:

```bash
# Format: source=target,source2=target2
export NORM_PATH_MAP="C:/Users/me=/home/me,//server/share=/mnt/share"
```

## Data Sources

The dashboard reads two data sources (**read-only**):

### Memory directory

Contains `.md` files with optional YAML frontmatter:

```markdown
---
name: My Memory
description: One-line description
type: user|feedback|project|reference
---

Content here...
```

`MEMORY.md` serves as the index file.

### history.jsonl

Claude Code's session history — one JSON object per line:

```json
{"display": "user message text", "timestamp": 1234567890000, "sessionId": "uuid", "project": "/path/to/project"}
```

## File Structure

```
claude-dashboard/
├── server.py          # Application (all code, templates, styles)
├── Dockerfile         # Python 3.12-slim image
├── docker-compose.yml # Quick-start compose
└── README.md
```

## License

MIT
