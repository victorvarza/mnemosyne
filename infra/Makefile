# Mnemosyne inference infra
#
#   p4de.24xlarge (8 x A100 80 GB)  ->  vLLM  ->  Qwen3-Coder-480B-A35B-Instruct (quantized)  ->  OpenCode CLI
#
# Server side (run ON the p4de host):   make run
# Client side (run on your laptop):     make tunnel SSH_HOST=ubuntu@<ip>   then   make opencode
#
# Every value below can be overridden on the command line, e.g.
#   make run MODEL_VARIANT=fp8 MAX_MODEL_LEN=65536

.PHONY: help run check-host storage install download serve start stop restart status logs \
	smoke-test connect-info tunnel opencode-config opencode clean clean-model guard-gpu-host ensure-uv api-key

SHELL := /bin/bash
.DEFAULT_GOAL := help
# uv's installer drops the binary in ~/.local/bin (or ~/.cargo/bin on older versions).
export PATH := $(HOME)/.local/bin:$(HOME)/.cargo/bin:$(PATH)

INFRA_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
SCRIPTS   := $(INFRA_DIR)/scripts

LOCALSSD ?= /mnt/localssd
ON ?= $(shell test -d $(LOCALSSD) && echo 1)

# ---------------------------------------------------------------------------
# Model selection  --  pick a model+quantization with MODEL_VARIANT=<value>:
#
#   Model                       MODEL_VARIANT   Quant   Weights  Fits on
#   --------------------------  --------------  ------  -------  -----------------
#   Qwen3-Coder-480B-A35B (MoE) awq (default)   AWQ-4   ~236 GB  p4de / p5 / p5en
#                               fp8             FP8     ~482 GB  p4de / p5 / p5en
#   Qwen3-Coder-30B-A3B   (MoE) 30b             BF16    ~61 GB   p4d+ (or g5*)
#                               30b-fp8         FP8     ~31 GB   g5.12xlarge
#   Qwen2.5-Coder-32B   (dense) 32b             BF16    ~64 GB   p4d / p5
#                               32b-awq         AWQ-4   ~20 GB   g5.12xlarge
#
#   MoE variants (480b/30b) use the `qwen3_coder` tool parser + expert-parallel.
#   The dense 32b variants use the `hermes` parser + expert-parallel OFF.
#   The smaller variants (30b*, 32b*) default to TP=4; override TP_SIZE=8 to use
#   all 8 GPUs. Every value is overridable, e.g.
#     make run MODEL_VARIANT=30b-fp8 TP_SIZE=4 MAX_MODEL_LEN=131072
# ---------------------------------------------------------------------------
MODEL_VARIANT ?= awq
ifeq ($(MODEL_VARIANT),awq)
MODEL_ID          ?= QuantTrio/Qwen3-Coder-480B-A35B-Instruct-AWQ
MODEL_DISK_GB     ?= 240
MAX_MODEL_LEN     ?= 131072
SERVED_MODEL_NAME ?= qwen3-coder-480b
MODEL_DISPLAY     ?= Qwen3-Coder-480B-A35B (awq, vLLM)
TOOL_CALL_PARSER  ?= qwen3_coder
else ifeq ($(MODEL_VARIANT),fp8)
MODEL_ID          ?= Qwen/Qwen3-Coder-480B-A35B-Instruct-FP8
MODEL_DISK_GB     ?= 490
MAX_MODEL_LEN     ?= 65536
SERVED_MODEL_NAME ?= qwen3-coder-480b
MODEL_DISPLAY     ?= Qwen3-Coder-480B-A35B (fp8, vLLM)
TOOL_CALL_PARSER  ?= qwen3_coder
else ifeq ($(MODEL_VARIANT),30b)
MODEL_ID          ?= Qwen/Qwen3-Coder-30B-A3B-Instruct
MODEL_DISK_GB     ?= 70
MAX_MODEL_LEN     ?= 65536
SERVED_MODEL_NAME ?= qwen3-coder-30b
MODEL_DISPLAY     ?= Qwen3-Coder-30B-A3B (bf16, vLLM)
TOOL_CALL_PARSER  ?= qwen3_coder
TP_SIZE           ?= 4
else ifeq ($(MODEL_VARIANT),30b-fp8)
MODEL_ID          ?= Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8
MODEL_DISK_GB     ?= 40
MAX_MODEL_LEN     ?= 65536
SERVED_MODEL_NAME ?= qwen3-coder-30b
MODEL_DISPLAY     ?= Qwen3-Coder-30B-A3B (fp8, vLLM)
TOOL_CALL_PARSER  ?= qwen3_coder
TP_SIZE           ?= 4
else ifeq ($(MODEL_VARIANT),32b-awq)
MODEL_ID          ?= Qwen/Qwen2.5-Coder-32B-Instruct-AWQ
MODEL_DISK_GB     ?= 30
MAX_MODEL_LEN     ?= 32768
SERVED_MODEL_NAME ?= qwen2.5-coder-32b
MODEL_DISPLAY     ?= Qwen2.5-Coder-32B (awq, vLLM)
TOOL_CALL_PARSER  ?= hermes
TP_SIZE           ?= 4
EXPERT_PARALLEL   ?= 0
else ifeq ($(MODEL_VARIANT),32b)
MODEL_ID          ?= Qwen/Qwen2.5-Coder-32B-Instruct
MODEL_DISK_GB     ?= 70
MAX_MODEL_LEN     ?= 32768
SERVED_MODEL_NAME ?= qwen2.5-coder-32b
MODEL_DISPLAY     ?= Qwen2.5-Coder-32B (bf16, vLLM)
TOOL_CALL_PARSER  ?= hermes
TP_SIZE           ?= 4
EXPERT_PARALLEL   ?= 0
else
$(error MODEL_VARIANT must be one of: awq, fp8, 30b, 30b-fp8, 32b-awq, 32b (got '$(MODEL_VARIANT)'))
endif
MODEL_REVISION    ?= main

# ---------------------------------------------------------------------------
# vLLM runtime
# ---------------------------------------------------------------------------
# Pinned to the release the AWQ checkpoint was validated against; override to upgrade.
VLLM_VERSION   ?= 0.10.1.1
# vLLM 0.10.x declares transformers>=4.55 with no upper bound, but transformers 5
# removed APIs it uses (e.g. all_special_tokens_extended). Keep these in sync
# with VLLM_VERSION when upgrading.
PIP_PINS       ?= "transformers>=4.55,<5"
PYTHON_VERSION ?= 3.12
TP_SIZE        ?= 8
# With TP=8 the MoE expert tensors cannot be split evenly -> expert parallel is required.
EXPERT_PARALLEL ?= 1
GPU_MEM_UTIL   ?= 0.90
MAX_NUM_SEQS   ?= 32
# Plain EC2: bind to localhost and reach it through `make tunnel`.
# Whenever the server is not localhost-only, an API key is generated automatically.
VLLM_HOST      ?= $(if $(ON),0.0.0.0,127.0.0.1)
VLLM_PORT      ?= 8000
VLLM_API_KEY   ?= $(shell cat "$(STATE_DIR)/api-key" 2>/dev/null)
EXTRA_VLLM_ARGS ?=
# Loading ~240-480 GB and capturing CUDA graphs can take a while.
START_TIMEOUT  ?= 3600

# ---------------------------------------------------------------------------
# Paths. Model weights go on local NVMe (ephemeral: re-downloaded after the
# instance stops / the container job terminates).
#   Container: /mnt/localssd (~530 GB per A100) - HF_HOME is preset by the platform
#   Plain EC2: /opt/dlami/nvme (instance store, see `make storage`)
#   Fallback:  $HOME/.cache
# ---------------------------------------------------------------------------
VENV         ?= $(INFRA_DIR)/.venv
STATE_DIR    ?= $(INFRA_DIR)/.vllm
PID_FILE     := $(STATE_DIR)/vllm.pid
LOG_FILE     := $(STATE_DIR)/vllm.log
NVME_MOUNT   ?= /opt/dlami/nvme
ifneq ($(ON),)
HF_HOME      ?= $(LOCALSSD)/.cache/huggingface
else
STORAGE_ROOT ?= $(shell if mountpoint -q $(NVME_MOUNT) 2>/dev/null; then echo $(NVME_MOUNT); else echo $(HOME)/.cache; fi)
HF_HOME      ?= $(STORAGE_ROOT)/huggingface
endif
LOCAL_URL    := http://127.0.0.1:$(VLLM_PORT)

VLLM_ARGS := \
	--served-model-name $(SERVED_MODEL_NAME) \
	--tensor-parallel-size $(TP_SIZE) \
	$(if $(filter 1,$(EXPERT_PARALLEL)),--enable-expert-parallel) \
	--max-model-len $(MAX_MODEL_LEN) \
	--gpu-memory-utilization $(GPU_MEM_UTIL) \
	--max-num-seqs $(MAX_NUM_SEQS) \
	--enable-auto-tool-choice \
	--tool-call-parser $(TOOL_CALL_PARSER) \
	--host $(VLLM_HOST) \
	--port $(VLLM_PORT) \
	$(EXTRA_VLLM_ARGS)

# The API key is passed via env (vLLM reads VLLM_API_KEY) so it never shows up in `ps`.
# Recursive (=) so a key generated by the `api-key` prerequisite is picked up.
SERVE_ENV = HF_HOME="$(HF_HOME)" HF_HUB_OFFLINE=1 VLLM_API_KEY="$(VLLM_API_KEY)"

# ---------------------------------------------------------------------------
# Client (laptop) settings
# ---------------------------------------------------------------------------
SSH_HOST          ?=
SSH_OPTS          ?=
LOCAL_PORT        ?= $(VLLM_PORT)
# Endpoint resolution for OpenCode (first match wins):
#   1. OPENCODE_BASE_URL=... on the command line
#   2. VLLM_HOST_URL from the environment or $(ENV_FILE)   (e.g. https://<pod>-8000.jobs.colligo.dev)
#   3. http://127.0.0.1:$(LOCAL_PORT)/v1                   (`make tunnel`)
# VLLM_API_KEY is read from the environment or $(ENV_FILE).
OPENCODE_BASE_URL ?=
ENV_FILE          ?= $(PROJECT_DIR)/.env
OPENCODE_CONFIG_FILE ?= $(INFRA_DIR)/opencode.vllm.json
OPENCODE_OUTPUT_LIMIT ?= 32768
PROJECT_DIR       ?= $(abspath $(INFRA_DIR)/..)

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'
	@echo
	@echo "  Model: $(MODEL_ID) (MODEL_VARIANT=$(MODEL_VARIANT)), context $(MAX_MODEL_LEN), TP=$(TP_SIZE)"

# ===========================================================================
# Server (p4de) targets
# ===========================================================================

run: ## [server] Install prerequisites, download the model, start vLLM, smoke-test
	@$(MAKE) --no-print-directory check-host
	@$(MAKE) --no-print-directory storage
	@# Sub-makes re-evaluate STORAGE_ROOT so a freshly mounted NVMe is picked up.
	@$(MAKE) --no-print-directory install
	@$(MAKE) --no-print-directory download
	@$(MAKE) --no-print-directory start
	@$(MAKE) --no-print-directory smoke-test
	@$(MAKE) --no-print-directory connect-info

guard-gpu-host:
	@if [ "$$(uname -s)" != "Linux" ] || ! command -v nvidia-smi &>/dev/null; then \
		echo "This target must run on the GPU host (p4de.24xlarge, Linux + NVIDIA driver)." >&2; \
		echo "From your laptop use: make tunnel SSH_HOST=... / make opencode" >&2; \
		exit 1; \
	fi

check-host: guard-gpu-host ## [server] Verify GPUs/driver/fabric manager, install OS deps and uv
	@"$(SCRIPTS)/check-host.sh" "$(TP_SIZE)"

storage: guard-gpu-host ## [server] Mount local NVMe instance store (RAID-0) for model weights
ifneq ($(ON),)
	@echo ">>> Container pod: using platform local SSD $(LOCALSSD) ($$(df -h --output=avail $(LOCALSSD) | tail -1 | tr -d ' ') free), HF_HOME=$(HF_HOME)"
else
	@"$(SCRIPTS)/mount-nvme.sh" "$(NVME_MOUNT)"
endif

api-key: ## [server] Generate an API key when vLLM is not bound to localhost only
	@if [ "$(VLLM_HOST)" != "127.0.0.1" ] && [ "$(VLLM_HOST)" != "localhost" ] \
		&& [ -z "$(VLLM_API_KEY)" ]; then \
		mkdir -p "$(STATE_DIR)"; \
		( umask 077; "$${PYTHON:-python3}" -c 'import secrets; print("sk-" + secrets.token_urlsafe(32))' > "$(STATE_DIR)/api-key" ); \
		echo ">>> vLLM listens on $(VLLM_HOST): generated API key in $(STATE_DIR)/api-key"; \
	fi

ensure-uv:
	@if ! command -v uv &>/dev/null; then \
		echo ">>> Installing uv..."; \
		curl -LsSf https://astral.sh/uv/install.sh | sh || exit 1; \
	fi; \
	command -v uv &>/dev/null || { echo "uv installed but not on PATH; open a new shell and retry" >&2; exit 1; }; \
	echo ">>> uv: $$(uv --version)"

install: guard-gpu-host ensure-uv ## [server] Create venv and install vLLM
	@stamp="$(VENV)/.mnemo-install"; want='vllm==$(VLLM_VERSION) $(PIP_PINS)'; \
	if [ -x "$(VENV)/bin/vllm" ] && [ "$$(cat "$$stamp" 2>/dev/null)" = "$$want" ]; then \
		echo ">>> Already installed in $(VENV): $$want"; \
		exit 0; \
	fi; \
	echo ">>> Installing $$want into $(VENV) (python $(PYTHON_VERSION))..."; \
	uv venv --allow-existing --seed --python "$(PYTHON_VERSION)" "$(VENV)" && \
	uv pip install --python "$(VENV)/bin/python" --torch-backend=auto \
		"vllm==$(VLLM_VERSION)" $(PIP_PINS) hf_transfer && \
	"$(VENV)/bin/python" -c 'import importlib.metadata as m; print(">>> transformers", m.version("transformers"), "| huggingface_hub", m.version("huggingface_hub"))' && \
	"$(VENV)/bin/python" -c 'import torch; assert torch.cuda.is_available(), "CUDA not available"; print(">>> torch", torch.__version__, "CUDA", torch.version.cuda, "GPUs:", torch.cuda.device_count())' && \
	echo "$$want" > "$$stamp"

download: guard-gpu-host ## [server] Download model weights to HF_HOME (resumable)
	@mkdir -p "$(HF_HOME)"
	@cache_dir="$(HF_HOME)/hub/models--$(subst /,--,$(MODEL_ID))"; \
	have=$$(du -s --block-size=1G "$$cache_dir" 2>/dev/null | cut -f1); have=$${have:-0}; \
	avail=$$(df --block-size=1G --output=avail "$(HF_HOME)" | tail -1 | tr -dc '0-9'); \
	if [ $$((have + avail)) -lt $(MODEL_DISK_GB) ]; then \
		echo "Not enough disk at $(HF_HOME): need ~$(MODEL_DISK_GB) GB, have $$avail GB free (+$$have GB already downloaded)." >&2; \
		echo "Run 'make storage' or set HF_HOME to a larger volume." >&2; \
		exit 1; \
	fi; \
	echo ">>> Downloading $(MODEL_ID)@$(MODEL_REVISION) (~$(MODEL_DISK_GB) GB) to $(HF_HOME)..."
	@HF_HOME="$(HF_HOME)" HF_HUB_ENABLE_HF_TRANSFER=1 HF_XET_HIGH_PERFORMANCE=1 "$(VENV)/bin/python" -c \
		'from huggingface_hub import snapshot_download; print(">>> Model at", snapshot_download("$(MODEL_ID)", revision="$(MODEL_REVISION)", max_workers=16))'

serve: guard-gpu-host install download api-key ## [server] Run vLLM in the foreground (Ctrl-C to stop)
	@echo ">>> vllm serve $(MODEL_ID) $(VLLM_ARGS)"
	@$(SERVE_ENV) exec "$(VENV)/bin/vllm" serve "$(MODEL_ID)" --revision "$(MODEL_REVISION)" $(VLLM_ARGS)

start: guard-gpu-host install download api-key ## [server] Start vLLM in the background and wait until healthy
	@mkdir -p "$(STATE_DIR)"
	@if curl -sf "$(LOCAL_URL)/health" &>/dev/null; then \
		echo ">>> vLLM already serving at $(LOCAL_URL)"; \
		exit 0; \
	fi; \
	if [ -f "$(PID_FILE)" ] && kill -0 "$$(cat "$(PID_FILE)")" 2>/dev/null; then \
		echo ">>> vLLM (pid $$(cat "$(PID_FILE)")) is still starting, waiting..."; \
	else \
		echo ">>> Starting vLLM: $(MODEL_ID) on $(VLLM_HOST):$(VLLM_PORT) (log: $(LOG_FILE))"; \
		rm -f "$(PID_FILE)"; \
		$(SERVE_ENV) setsid nohup bash -c 'echo $$$$ > "$(PID_FILE)"; exec "$(VENV)/bin/vllm" serve "$(MODEL_ID)" --revision "$(MODEL_REVISION)" $(VLLM_ARGS)' \
			>> "$(LOG_FILE)" 2>&1 < /dev/null & \
		for i in $$(seq 1 20); do [ -s "$(PID_FILE)" ] && break; sleep 0.5; done; \
	fi; \
	pid=$$(cat "$(PID_FILE)"); deadline=$$((SECONDS + $(START_TIMEOUT))); \
	while [ $$SECONDS -lt $$deadline ]; do \
		if curl -sf "$(LOCAL_URL)/health" &>/dev/null; then \
			echo ">>> vLLM is ready at $(LOCAL_URL) after $${SECONDS}s"; \
			exit 0; \
		fi; \
		if ! kill -0 "$$pid" 2>/dev/null; then \
			echo "vLLM exited during startup. Last log lines:" >&2; \
			tail -n 60 "$(LOG_FILE)" >&2; \
			rm -f "$(PID_FILE)"; \
			exit 1; \
		fi; \
		sleep 15; \
		echo "    ... loading ($${SECONDS}s) $$(tail -n 1 "$(LOG_FILE)" | cut -c1-120)"; \
	done; \
	echo "vLLM not healthy after $(START_TIMEOUT)s; see $(LOG_FILE)" >&2; \
	exit 1

stop: ## [server] Stop the background vLLM server
	@if [ -f "$(PID_FILE)" ] && kill -0 "$$(cat "$(PID_FILE)")" 2>/dev/null; then \
		pid=$$(cat "$(PID_FILE)"); \
		echo ">>> Stopping vLLM (pid $$pid)..."; \
		kill -TERM -- "-$$pid" 2>/dev/null || kill -TERM "$$pid"; \
		for i in $$(seq 1 60); do kill -0 "$$pid" 2>/dev/null || break; sleep 1; done; \
		if kill -0 "$$pid" 2>/dev/null; then kill -KILL -- "-$$pid" 2>/dev/null || kill -KILL "$$pid"; fi; \
		echo ">>> Stopped"; \
	else \
		echo ">>> vLLM is not running"; \
	fi; \
	rm -f "$(PID_FILE)"

restart: ## [server] Restart vLLM
	@$(MAKE) --no-print-directory stop
	@$(MAKE) --no-print-directory start

status: ## [server] Show vLLM process, health and GPU memory
	@if [ -f "$(PID_FILE)" ] && kill -0 "$$(cat "$(PID_FILE)")" 2>/dev/null; then \
		echo ">>> process: running (pid $$(cat "$(PID_FILE)"))"; \
	else \
		echo ">>> process: not running"; \
	fi
	@if curl -sf "$(LOCAL_URL)/health" &>/dev/null; then echo ">>> health:  OK ($(LOCAL_URL))"; else echo ">>> health:  DOWN"; fi
	@command -v nvidia-smi &>/dev/null && nvidia-smi --query-gpu=index,memory.used,memory.total,utilization.gpu --format=csv || true

logs: ## [server] Follow the vLLM log
	@tail -n 100 -f "$(LOG_FILE)"

smoke-test: ## [server] Chat + tool-calling request against the running server
	@PYTHON="$$([ -x "$(VENV)/bin/python" ] && echo "$(VENV)/bin/python" || echo python3)" \
	VLLM_API_KEY="$(VLLM_API_KEY)" \
	"$(SCRIPTS)/smoke-test.sh" "$(LOCAL_URL)" "$(SERVED_MODEL_NAME)"

connect-info: ## [server] Print how to connect OpenCode from your laptop
	@echo; echo "vLLM is serving '$(SERVED_MODEL_NAME)' on $(VLLM_HOST):$(VLLM_PORT)."; \
	echo "On your laptop, from mnemosyne/infra:"; \
	if [ -n "$(ON)" ]; then \
		url="https://$$(hostname)-$(VLLM_PORT).jobs.colligo.dev/v1"; \
		echo "  (VPN required)"; \
		echo "  export VLLM_API_KEY=<contents of $(STATE_DIR)/api-key>"; \
		echo "  make opencode OPENCODE_BASE_URL=$$url MAX_MODEL_LEN=$(MAX_MODEL_LEN) MODEL_VARIANT=$(MODEL_VARIANT)"; \
		echo "  Alternative over SSH (after 'aip job configure ssh <job>'):"; \
		echo "    make tunnel SSH_HOST=$$(hostname)   then   make opencode"; \
	else \
		ip=$$(curl -sf -m 2 http://checkip.amazonaws.com 2>/dev/null || hostname -I | awk '{print $$1}'); \
		echo "  1) make tunnel SSH_HOST=$$(whoami)@$$ip      # keep running"; \
		echo "  2) make opencode MAX_MODEL_LEN=$(MAX_MODEL_LEN) MODEL_VARIANT=$(MODEL_VARIANT)"; \
		if [ -n "$(VLLM_API_KEY)" ]; then echo "     (export VLLM_API_KEY=<same key> first)"; fi; \
	fi

# ===========================================================================
# Client (laptop) targets
# ===========================================================================

tunnel: ## [client] SSH port-forward localhost:LOCAL_PORT -> vLLM (SSH_HOST=user@host)
	@if [ -z "$(SSH_HOST)" ]; then echo "Set SSH_HOST, e.g. make tunnel SSH_HOST=ubuntu@1.2.3.4 SSH_OPTS='-i ~/.ssh/key.pem'" >&2; exit 1; fi
	@echo ">>> Forwarding 127.0.0.1:$(LOCAL_PORT) -> $(SSH_HOST):127.0.0.1:$(VLLM_PORT) (Ctrl-C to close)"
	@ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 $(SSH_OPTS) \
		-L "$(LOCAL_PORT):127.0.0.1:$(VLLM_PORT)" "$(SSH_HOST)"

# Shell prelude for client targets: loads $(ENV_FILE) and sets $base (OpenAI base URL).
client_env = if [ -f "$(ENV_FILE)" ]; then set -a; . "$(ENV_FILE)"; set +a; fi; \
	base="$(OPENCODE_BASE_URL)"; \
	if [ -z "$$base" ] && [ -n "$${VLLM_HOST_URL:-}" ]; then base="$${VLLM_HOST_URL%/}"; base="$${base%/v1}/v1"; fi; \
	base="$${base:-http://127.0.0.1:$(LOCAL_PORT)/v1}"

opencode-config: ## [client] Generate the OpenCode provider config for the vLLM endpoint
	@$(client_env); \
	"$(SCRIPTS)/opencode-config.sh" "$(OPENCODE_CONFIG_FILE)" "$$base" \
		"$(SERVED_MODEL_NAME)" "$(MODEL_DISPLAY)" \
		"$(MAX_MODEL_LEN)" "$(OPENCODE_OUTPUT_LIMIT)"

opencode: opencode-config ## [client] Launch OpenCode in PROJECT_DIR (reads VLLM_HOST_URL/VLLM_API_KEY from .env)
	@command -v opencode &>/dev/null || { echo "opencode not found: https://opencode.ai/docs" >&2; exit 1; }
	@$(client_env); \
	echo ">>> vLLM endpoint: $$base$$([ -f "$(ENV_FILE)" ] && echo "  (env: $(ENV_FILE))")"; \
	if ! curl -sf -m 10 "$${base%/v1}/health" &>/dev/null; then \
		echo "vLLM not reachable at $$base. Check VLLM_HOST_URL in $(ENV_FILE), VPN, or 'make tunnel SSH_HOST=...'." >&2; \
		exit 1; \
	fi; \
	code=$$(curl -s -m 10 -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $${VLLM_API_KEY:-EMPTY}" "$$base/models"); \
	if [ "$$code" != "200" ]; then \
		echo "vLLM rejected the API key (HTTP $$code). Set VLLM_API_KEY in $(ENV_FILE) to the contents of infra/.vllm/api-key on the server." >&2; \
		exit 1; \
	fi; \
	cd "$(PROJECT_DIR)" && VLLM_API_KEY="$${VLLM_API_KEY:-EMPTY}" OPENCODE_CONFIG="$(OPENCODE_CONFIG_FILE)" exec opencode

# ===========================================================================

clean: stop ## Stop vLLM and remove the venv and runtime state (keeps model weights)
	rm -rf "$(VENV)" "$(STATE_DIR)" "$(OPENCODE_CONFIG_FILE)"

clean-model: ## Delete the downloaded model weights for MODEL_VARIANT
	rm -rf "$(HF_HOME)/hub/models--$(subst /,--,$(MODEL_ID))"
