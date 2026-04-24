# Nexus Automation Node

A self-hosted automation engine for **Project Nexus**, powered by **n8n** and deployed via Docker.  
This service handles workflow execution, event processing, task orchestration, and all automated integrations within the Nexus ecosystem.

---

## 🚀 Features

- **Dockerized n8n stack** for simple, reproducible deployment  
- **Environment template (`.env.example`)** for quick configuration  
- **Optional Traefik / Cloudflare / NGINX reverse proxy support**  
- **Automatic backups** (MariaDB/PostgreSQL optional)  
- **API-ready** for integration with:
  - Nexus Brainstem (validation layer)
  - Nexus Cortex (LLM reasoning engine)
  - NAS memory node (semantic/episodic storage)
  - Local/remote Ollama or TRT-LLM runtimes
- **Secure external access** with tokens + HTTPS  
- **Designed for long-running stable uptime**

---

## 📂 Repository Structure

nexus-automation-node/
│
├── docker-compose.yml
├── Dockerfile (optional if using n8n official image)
├── .env.example
├── .gitignore
│
├── proxy/
│ ├── traefik.yml
│ ├── dynamic/
│ └── certificates/
│
├── workflows/ (exported n8n workflow JSON files)
├── scripts/ (backup, restore, maintenance utilities)
│
└── README.md

## 🐳 Deployment

### Prerequisites
- Docker + Docker Compose installed  
- A domain or subdomain if using HTTPS  
- (Optional) Cloudflare Tunnel or Traefik proxy

### Quick Start

1. Copy the example environment file:

   cp .env.example .env
Edit values as needed:


Copy code
nano .env
Start the stack:

Copy code
docker compose up -d
Access n8n at:

Copy code
http://localhost:5678
or your reverse-proxied domain:

Copy code
https://n8n.example.com

🔌 Integration With Local LLMs

nexus-automation-node can connect to:
Ollama running on another machine or container
Nexus Cortex runtime
Any OpenAI-compatible LLM server

Example HTTP Request node (inside n8n):

Copy code
POST http://<machine-ip>:11434/api/generate
{
  "model": "llama2",
  "prompt": "Hello from Nexus automation node!"
}

🔒 Security
Use strong JWT + Basic Auth tokens

Always reverse proxy behind HTTPS when exposed to the internet
Rotate encryption keys yearly (scripts included)
Store secrets in .env, never in workflows

💾 Backups
To back up workflow + credentials:


Copy code
docker exec n8n sh -c "tar czf /home/node/.n8n_backup.tar.gz /home/node/.n8n"
docker cp n8n:/home/node/.n8n_backup.tar.gz .
To restore:

Copy code
docker cp .n8n_backup.tar.gz n8n:/home/node
docker exec n8n tar xzf /home/node/.n8n_backup.tar.gz -C /

🧠 About Project Nexus
This repository is one node within Project Nexus — a modular, biologically-inspired distributed cognition system composed of:
Cortex (4090) – reasoning engine
Brainstem (4070) – validation and routing
NAS Memory Node – semantic/episodic knowledge store
Peripheral Jetson Nanos – sensory modules
Automation Node (this repo) – workflow orchestration layer
Each node is isolated, autonomous, and composable.

📜 License
MIT License — free to use, modify, deploy, and integrate.

