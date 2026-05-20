#!/usr/bin/env bash
# =============================================================================
# Nexus Cortex LLM Setup — Ubuntu 22.04 WSL2
# Run this inside Ubuntu 22.04 WSL2 terminal:
#   wsl -d Ubuntu-22.04
#   bash /mnt/c/Users/Drama/Desktop/Nexus-Automation-Node/scripts/setup-cortex-llm.sh
# =============================================================================
set -e

MODEL="nm-testing/Qwen3-Coder-30B-A3B-Instruct-W4A16-awq"
VLLM_PORT=8001
VENV_DIR="$HOME/cortex-llm"
SERVICE_NAME="cortex-llm"

echo "=============================================="
echo " Nexus Cortex LLM Setup"
echo " Model : $MODEL"
echo " Port  : $VLLM_PORT"
echo " Venv  : $VENV_DIR"
echo "=============================================="
echo ""

# ------------------------------------------------------------------------------
# Step 1 — System dependencies
# ------------------------------------------------------------------------------
echo "[1/6] Installing system packages..."
sudo apt-get update -q
sudo apt-get install -y -q python3-pip python3-venv git curl
echo "      Done."

# ------------------------------------------------------------------------------
# Step 2 — Python virtual environment
# ------------------------------------------------------------------------------
echo "[2/6] Creating virtual environment at $VENV_DIR..."
python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"
pip install --upgrade pip wheel setuptools -q
echo "      Done."

# ------------------------------------------------------------------------------
# Step 3 — Install vLLM
# vLLM pip package ships its own CUDA runtime — no separate CUDA install needed.
# WSL2 libcuda.so bridge handles the driver communication.
# ------------------------------------------------------------------------------
echo "[3/6] Installing vLLM (this downloads PyTorch + CUDA — may take 10-15 min)..."
pip install vllm
echo "      Done."

# ------------------------------------------------------------------------------
# Step 4 — Verify GPU is visible to PyTorch / vLLM
# ------------------------------------------------------------------------------
echo "[4/6] Verifying GPU access..."
python3 - <<'EOF'
import torch
if not torch.cuda.is_available():
    print("ERROR: CUDA not available to PyTorch. Check WSL2 NVIDIA driver.")
    exit(1)
print(f"      GPU: {torch.cuda.get_device_name(0)}")
print(f"      VRAM: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f} GB")
print(f"      CUDA: {torch.version.cuda}")
EOF

# ------------------------------------------------------------------------------
# Step 5 — Pre-download the model to HuggingFace cache
# ~18 GB download — grab a coffee.
# ------------------------------------------------------------------------------
echo "[5/6] Downloading model $MODEL (~18 GB)..."
python3 - <<EOF
from huggingface_hub import snapshot_download
snapshot_download(repo_id="$MODEL", ignore_patterns=["*.bin"])
print("      Model download complete.")
EOF

# ------------------------------------------------------------------------------
# Step 6 — Create systemd service for auto-start
# Ubuntu 22.04 WSL2 supports systemd if enabled in /etc/wsl.conf
# ------------------------------------------------------------------------------
echo "[6/6] Creating systemd service..."

# Ensure systemd is enabled in WSL2
if ! grep -q "systemd=true" /etc/wsl.conf 2>/dev/null; then
    echo "      Enabling systemd in /etc/wsl.conf..."
    sudo tee -a /etc/wsl.conf > /dev/null <<'WSLCONF'
[boot]
systemd=true
WSLCONF
    echo "      NOTE: WSL2 must be restarted for systemd to take effect."
    echo "      After this script finishes, run: wsl --shutdown"
    echo "      Then reopen Ubuntu-22.04 and run: sudo systemctl enable --now cortex-llm"
fi

# Write the service file
sudo tee /etc/systemd/system/${SERVICE_NAME}.service > /dev/null <<EOF
[Unit]
Description=Nexus Cortex LLM — vLLM serving ${MODEL}
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$HOME
Environment="HF_HOME=$HOME/.cache/huggingface"
ExecStart=${VENV_DIR}/bin/vllm serve ${MODEL} \\
    --port ${VLLM_PORT} \\
    --host 0.0.0.0 \\
    --max-model-len 32768 \\
    --gpu-memory-utilization 0.90 \\
    --served-model-name cortex
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

echo "      Service file written to /etc/systemd/system/${SERVICE_NAME}.service"

# Try to reload/enable now (only works if systemd is already running)
if pidof systemd &>/dev/null; then
    sudo systemctl daemon-reload
    sudo systemctl enable ${SERVICE_NAME}
    echo ""
    echo "=============================================="
    echo " Setup complete! Starting service..."
    echo "=============================================="
    sudo systemctl start ${SERVICE_NAME}
    echo ""
    echo " Watch logs:  journalctl -u cortex-llm -f"
    echo " Test:        curl http://localhost:8001/v1/models"
    echo " From n8n:    http://host.docker.internal:8001"
else
    echo ""
    echo "=============================================="
    echo " Setup complete!"
    echo "=============================================="
    echo ""
    echo " Systemd not running yet. Next steps:"
    echo "   1. Exit WSL2:       exit"
    echo "   2. Restart WSL2:    wsl --shutdown   (run in PowerShell/CMD)"
    echo "   3. Reopen Ubuntu:   wsl -d Ubuntu-22.04"
    echo "   4. Enable service:  sudo systemctl enable --now cortex-llm"
    echo "   5. Watch logs:      journalctl -u cortex-llm -f"
    echo "   6. Test:            curl http://localhost:8001/v1/models"
    echo "   7. From n8n:        http://host.docker.internal:8001"
fi
