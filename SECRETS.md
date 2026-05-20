# Secrets handling

## Status

- No secret has ever been committed to either the outer `ProjectNexus` repo or the subtree-merged `automation/` path. Verified via filename search and content pickaxe across all branches for every known key prefix.
- `.gitignore` blocks `.env`, `*.env`, `.mcp.json`, `.key`, `.pem`, `Access_Token.txt`, `Google Keys.txt`, and the n8n backup tarballs. A reflexive `git add .` cannot catastrophize.
- `.gitignore` itself contains **only filename patterns**, never key values.

## Rotate these now

These flowed through a Claude Code session and sit in plaintext `.env` files on disk. Rotation is precautionary.

| Provider | Rotation path |
|---|---|
| Google OAuth client secret | console.cloud.google.com/apis/credentials → edit client → "Reset Client Secret" |
| Gemini | aistudio.google.com/apikey |
| OpenAI | platform.openai.com/api-keys |
| Anthropic | console.anthropic.com/settings/keys |
| Cloudflare tunnel | Zero Trust → Networks → Tunnels → rotate token |
| n8n API JWT | n8n UI → Settings → API → revoke + reissue |

## Target architecture: SOPS + age

Why not "just `.gitignore`": gitignore only prevents accidents. It stops files from being staged. It does nothing about plaintext sitting on disk, nothing about multi-host distribution, nothing about auditability. Works fine for a single laptop, breaks the moment you want four machines sharing secrets.

**SOPS + age** keeps encrypted secrets in git. Each machine decrypts with its own private key. Cross-host secret rollout becomes `git pull` + `sops --decrypt`. No running service to babysit. Written by Mozilla, now CNCF-graduated. Battle-tested.

### Setup (one time)

**1. Install tooling.** Pick one per tool.

```bash
# Via Scoop (recommended on Windows; add the extras bucket once):
scoop bucket add extras
scoop install age sops gitleaks

# Or via winget:
winget install FiloSottile.age
winget install getsops.sops
winget install gitleaks.gitleaks

# Or manual binaries from GitHub releases if you prefer.

# Python tooling for the pre-commit hook runner:
pip install pre-commit
```

**2. Generate the age keypair.**

```bash
mkdir -p "$HOME/.config/sops/age"
age-keygen -o "$HOME/.config/sops/age/keys.txt"
```

The file contains one line starting `# public key: age1...` and one line starting `AGE-SECRET-KEY-...`.

**3. Copy the private key into your password manager.**

Paste the `AGE-SECRET-KEY-...` line into a Bitwarden or 1Password secure note titled `Nexus age private key`. The file on disk is the working copy; the password manager is the backup for when you provision the 4070, the NAS, and future nodes.

**4. Wire the public key into `.sops.yaml`.**

Open `.sops.yaml` at the repo root. Replace every `age1REPLACE_ME_WITH_YOUR_PUBLIC_KEY` with the `age1...` value from step 2.

**5. Install the pre-commit hooks.**

```bash
cd C:/Users/Drama/Desktop/Nexus
pre-commit install
```

Now every `git commit` runs gitleaks plus a SOPS sanity check locally.

### Daily workflow

### Naming convention

| File | Git | Purpose |
|---|---|---|
| `automation/.env` | ignored | Plaintext working copy. Compose reads this directly. Lives on the host only. |
| `automation/.env.sops` | tracked | Age-encrypted ciphertext. Source of truth in git. Rolls to future hosts. |
| `automation/.env.example` | tracked | Placeholder template with blank values. For humans reading the repo. |

### Daily workflow

**Seeding `.env.sops` from an edited plaintext `.env`:**

```powershell
sops --encrypt --input-type dotenv --output-type dotenv --output automation/.env.sops automation/.env
git add automation/.env.sops
git commit -m "secrets(automation): rotate keys"
```

**Pulling secrets onto a fresh machine:**

```powershell
git clone <repo>
# Copy the age private key to %USERPROFILE%\.config\sops\age\keys.txt (Windows)
# or $HOME/.config/sops/age/keys.txt (Linux/macOS), permissions 600.

sops --decrypt --input-type dotenv --output-type dotenv --output automation/.env automation/.env.sops
cd automation ; docker compose up -d
```

**Editing secrets directly without writing plaintext to disk longer than needed:**

```powershell
sops automation/.env.sops
# opens $EDITOR on decrypted content. On save, sops re-encrypts. Never touches .env.
```

After editing `.env.sops`, refresh the local plaintext so compose sees the new values:

```powershell
sops --decrypt --input-type dotenv --output-type dotenv --output automation/.env automation/.env.sops
docker compose --project-directory automation restart
```

### Why PowerShell redirection is not used

Windows PowerShell 5.1 writes UTF-16 LE by default when you `>` a file, which sops's dotenv parser chokes on. Always use `sops ... --output <path> <input>` instead of `sops ... <input> > <path>`. The PowerShell tool that shipped the repo-level `profile.ps1` template (if any) should wrap this for you.

### Adding a second host

When the 4070 comes back online, give it its own age keypair and add its public key to `.sops.yaml` as an additional `age:` entry. Then re-encrypt:

```bash
sops updatekeys automation/.env
git commit -am "secrets: grant 4070 decryption on automation env"
```

Now both the 4090 and the 4070 can decrypt with their respective private keys. Cross-signing keys this way scales cleanly across a cluster without ever sharing a private key.

## What's already wired in this repo

| File | Purpose |
|---|---|
| `.gitignore` | Blocks accidental staging of `.env`, `Google Keys.txt`, `.mcp.json`, model weights, Office lockfiles. |
| `.sops.yaml` | Routes which age recipients encrypt which paths. Needs your public key pasted in. |
| `.pre-commit-config.yaml` | gitleaks + SOPS-check + basic hygiene hooks. Activate with `pre-commit install`. |
| `automation/.env.example` | Variable-name template with blank values. Tracked. |
| `automation/.env` | You create this locally. Gets encrypted before commit. Gitignored in its plaintext form. |

## Level-up paths (when you feel friction)

- **Infisical (self-hosted):** web UI, per-environment scoping, audit log. Worth it when more than five services need the same key.
- **HashiCorp Vault:** full secret-management platform. Overkill until there are humans on a team.
- **1Password CLI with service accounts:** if you already live in 1Password, `op inject` substitutes placeholders at runtime from template files. Alternative to SOPS if you want zero local secret files.

For your current scale (solo, three to five services, home lab going multi-host) SOPS + age is the correct ceiling. Don't escalate until something actually hurts.
