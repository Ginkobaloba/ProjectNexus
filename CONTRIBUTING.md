# Contributing to Project Nexus

Thank you for your interest in contributing to Project Nexus —  
a distributed, multi-node cognitive architecture composed of:

- **Brainstem nodes** (embedding + short-term memory)
- **NAS memory node** (semantic + episodic LTM)
- **Future Cortex nodes** (reasoning + planning)
- **Peripheral Jetson nodes** (sensory input streams)

This document explains the guidelines, best practices, and workflow expected of all contributors.

---

## 🧩 Architecture Overview

Nexus is structured into major components:

core/ # Shared utilities (NAS client, session, timing)
nodes/
brainstem_XXXX/ # Embedding nodes
nas-memory/ # Long-term memory store
cortex_XXXX/ # Future reasoning nodes
docker/ # Dockerfiles and compose orchestration
data/ # Local runtime memory (ignored by Git)


## 🧱 Development Setup

### Requirements:
- Python 3.11+
- Docker + Docker Compose
- Git LFS installed (`git lfs install`)
- VSCode (recommended)

### Steps:
git clone https://github.com/ginkobaloba/ProjectNexus.git
cd ProjectNexus
pip install -r requirements.txt

### For Nodes:
docker compose up brainstem
docker compose up nas

### ✍ Code Style:
To maintain consistency:
Use Black for formatting
Use Ruff for linting
Keep imports sorted (isort)
Include comments describing intent, not just implementation
Keep functions short and composable
Pre-commit hooks will be added soon to enforce formatting automatically.

### 🧠 Making Changes
1. Fork + Branch
git checkout -b feature/some-improvement

2. Write clean, well-commented code
Anything affecting memory, retrieval, or node interaction must explain:
Why the change exists
How it affects the cognitive system
Any cross-node implications

3. Test nodes locally using Docker
Ensure both brainstem + NAS start cleanly:
docker compose build brainstem
docker compose build nas
docker compose up

4. Commit with clear messages

Good examples:
Add enriched episodic logging with timestamps and session IDs
Refactor NAS semantic store for new Chroma API
Wire brainstem to NAS LTM pipeline

5. Open a Pull Request
Include:
Summary of purpose
Screenshots/logs if behavior changed
Mention affected nodes

### 🧪 Tests:
Automated tests will be added (pytest + Docker harness).
For now, manual testing of:
/embed
/semantic/write
/episodic/write
/episodic/list
is required before PR approval.

### 🛡 Security Considerations:
Do not commit secrets
Do not commit embeddings or Chroma directories
Do not expose Docker ports publicly
Treat memory stores as sensitive data
See SECURITY.md.

### 🤝 Contributor Recognition:
All contributors will be acknowledged in:
The README
Future Nexus architecture papers
The long-term evolution timeline
Your work becomes part of a living synthetic cognitive system.