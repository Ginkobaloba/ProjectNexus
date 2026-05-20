# Project Nexus — Security Policy

Project Nexus is a distributed cognitive architecture composed of multiple cooperating nodes
(brainstem, cortex, NAS memory, and future sensor/agent modules). Because the system stores embeddings,
episodic logs, and sensitive operational data, security is a first-class concern.

---

## 🔐 Supported Versions
Security fixes apply to the main development branch unless otherwise stated.

---

## 🔒 Key Security Principles

### 1. **Never store secrets in the repository**
All API keys, credentials, access tokens, and environment-specific configuration must be stored in:

- `.env` files excluded via `.gitignore`
- Docker environment variables
- OS-level secret stores

**Never commit:**
- Access_Token.txt
- `.env`
- HuggingFace tokens
- database passwords
- model API keys

---

## 🧱 2. Node Isolation & Network Boundaries

Each Nexus node (brainstem, NAS, cortex, Jetson agents) must run within isolated Docker containers
or secured OS processes.

**Only the following ports should be exposed:**

- Brainstem: `5001` (internal only)
- NAS Memory: `5002` (internal only)
- Cortex: To be determined
- API Gateway: Exposed only when intentionally enabled

**No container should be exposed publicly unless routed through a secure API gateway.**

---

## 🧬 3. Data Sensitivity: Embeddings & Episodic Memory

Semantic and episodic memory may contain:

- user text
- derived embeddings
- behavioral logs
- timestamps
- system actions

These represent sensitive cognitive data.

**ChromaDB persistence must never be committed to Git or shared publicly.**
It is already excluded via `.gitignore`.

---

## 🔁 4. Secure Inter-Node Communication

All nodes communicate over internal Docker networks by default.

In production environments, the following should be enforced:

- Mutual TLS between nodes
- Network segmentation
- Auth tokens for node-to-node requests
- Rate limiting on public API routes

---

## 🛡 5. Reporting a Vulnerability

If you believe you have discovered a security issue with Project Nexus:

1. **Do NOT file a public GitHub issue.**
2. Email the maintainer directly:
   **dramattick1@gmail.com**
3. Provide:
   - A description of the issue
   - Steps to reproduce
   - Potential impact
   - Suggested fixes (if known)

The maintainer (or team, in the future) will respond promptly.

---

## 🏗 6. Future Security Enhancements (Planned)

- Node-to-node encryption (mTLS)
- Authenticated access tokens for internal nodes
- Permission system for memory read/write
- Sandboxed execution for cortex reasoning kernels
- Signed model artifacts
- Automated dependency vulnerability scanning

---

**Project Nexus is being built as a trustworthy, privacy-respecting, secure cognitive system.
Security is not optional — it is foundational.**
