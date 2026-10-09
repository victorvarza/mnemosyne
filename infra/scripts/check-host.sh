#!/usr/bin/env bash
# Verify the GPU host is fit to serve Qwen3-Coder-480B with vLLM and install
# the OS-level prerequisites (compiler toolchain for Triton JIT, curl, uv).
# Usage: check-host.sh <required_gpu_count>
set -euo pipefail

REQUIRED_GPUS="${1:-8}"
MIN_DRIVER_MAJOR=550

SUDO=""
[ "$(id -u)" -ne 0 ] && SUDO="sudo"

die()  { echo "ERROR: $*" >&2; exit 1; }
warn() { echo "WARNING: $*" >&2; }

pkg_install() {
  if command -v apt-get &>/dev/null; then
    $SUDO apt-get update -qq
    $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "$@"
  elif command -v dnf &>/dev/null; then
    $SUDO dnf install -y -q "$@"
  else
    die "No supported package manager (apt-get/dnf) to install: $*"
  fi
}

[ "$(uname -s)" = "Linux" ] || die "Must run on Linux (the p4de host)."

# --- NVIDIA driver & GPUs ---------------------------------------------------
command -v nvidia-smi &>/dev/null || die "nvidia-smi not found. Use an AWS Deep Learning AMI (Ubuntu) or install the NVIDIA driver."

gpu_count=$(nvidia-smi -L | wc -l)
echo ">>> GPUs detected: $gpu_count (need $REQUIRED_GPUS)"
nvidia-smi --query-gpu=index,name,memory.total,driver_version --format=csv,noheader | sed 's/^/    /'
[ "$gpu_count" -ge "$REQUIRED_GPUS" ] || die "Need at least $REQUIRED_GPUS GPUs for tensor parallelism."

driver=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -1)
if [ "${driver%%.*}" -lt "$MIN_DRIVER_MAJOR" ]; then
  warn "NVIDIA driver $driver is older than $MIN_DRIVER_MAJOR; recent vLLM/PyTorch CUDA 12.8 wheels may fail. Upgrade the driver or use a newer DLAMI."
fi

# --- NVSwitch fabric manager (required on A100 SXM / p4d / p4de) -----------
if [ ! -d /run/systemd/system ]; then
  # Container (e.g. Kubernetes job pod): fabric manager runs on the host node.
  echo ">>> Running in a container without systemd; fabric manager is managed by the host"
elif systemctl list-unit-files 2>/dev/null | grep -q '^nvidia-fabricmanager'; then
  if ! systemctl is-active --quiet nvidia-fabricmanager; then
    echo ">>> Starting nvidia-fabricmanager..."
    $SUDO systemctl enable --now nvidia-fabricmanager
  fi
  echo ">>> nvidia-fabricmanager: active"
else
  warn "nvidia-fabricmanager not installed. On NVSwitch systems (p4de) CUDA init fails without it; install the package matching driver $driver."
fi

# --- OS packages ------------------------------------------------------------
missing=()
command -v gcc  &>/dev/null || missing+=(gcc)
command -v curl &>/dev/null || missing+=(curl)
if [ "${#missing[@]}" -gt 0 ]; then
  echo ">>> Installing OS packages: ${missing[*]}"
  if command -v apt-get &>/dev/null; then
    pkg_install build-essential curl
  else
    pkg_install gcc gcc-c++ make curl
  fi
fi

# --- uv ---------------------------------------------------------------------
if ! command -v uv &>/dev/null; then
  echo ">>> Installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
echo ">>> uv: $(uv --version)"
echo ">>> Host checks passed"
