.PHONY: run worker-setup install-ollama start-ollama pull-models client-setup \
	client-install-uv client-install client-demo client-test client-lint client-scan \
	client-redteam client-security client-train client-benchmark client-lifecycle \
	install demo test lint scan redteam security clean help \
	opencode opencode-config

SHELL := /bin/bash
MNEMO_OLLAMA_URL ?= http://localhost:11434
MNEMO_LLM_MODEL ?= qwen2.5:7b
MNEMO_EMBED_MODEL ?= nomic-embed-text
OLLAMA_HOST ?= 0.0.0.0:11434
# The local endpoint used to check and provision the listener above. Overriding
# OLLAMA_HOST automatically preserves its port; override OLLAMA_URL only when
# the worker must be reached through a different local address.
OLLAMA_URL ?= http://127.0.0.1:$(lastword $(subst :, ,$(OLLAMA_HOST)))

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

run: ## Provision and run the Ubuntu Ollama inference worker
	@$(MAKE) --no-print-directory install-ollama
	@$(MAKE) --no-print-directory start-ollama
	@$(MAKE) --no-print-directory pull-models

worker-setup: run ## Alias for provisioning the Ubuntu inference worker

install-ollama: ## Install Ollama for the Ubuntu inference worker
	@if ! command -v ollama &>/dev/null; then \
		echo ">>> Installing Ollama..."; \
		curl -fsSL https://ollama.com/install.sh | sh; \
	else \
		echo ">>> Ollama already installed: $$(ollama --version)"; \
	fi

start-ollama: ## Start Ollama for the inference worker
	@if curl -sf "$(OLLAMA_URL)/api/tags" &>/dev/null; then \
		echo ">>> Ollama already running at $(OLLAMA_URL)"; \
		exit 0; \
	fi; \
	echo ">>> Starting Ollama server on $(OLLAMA_HOST) (checking $(OLLAMA_URL))..."; \
	nohup env OLLAMA_HOST="$(OLLAMA_HOST)" ollama serve > .ollama-worker.log 2>&1 & \
	for i in $$(seq 1 30); do \
		if curl -sf "$(OLLAMA_URL)/api/tags" &>/dev/null; then \
			echo ">>> Ollama is ready at $(OLLAMA_URL)"; \
			exit 0; \
		fi; \
		sleep 1; \
	done; \
	echo "Ollama did not become ready at $(OLLAMA_URL); verify OLLAMA_HOST and OLLAMA_URL, then see .ollama-worker.log" >&2; \
	exit 1

pull-models: ## Pull MNEMO_LLM_MODEL and MNEMO_EMBED_MODEL on the worker
	@for model in "$(MNEMO_LLM_MODEL)" "$(MNEMO_EMBED_MODEL)"; do \
		echo ">>> Pulling $$model..."; \
		OLLAMA_HOST="$(OLLAMA_URL)" ollama pull "$$model" || exit $$?; \
	done

client-setup: client-install-uv client-install ## Install local mnemo CLI dependencies only

client-install-uv: ## Install uv for the local mnemo CLI
	@if ! command -v uv &>/dev/null; then \
		echo ">>> Installing uv..."; \
		curl -LsSf https://astral.sh/uv/install.sh | sh; \
		echo 'export PATH="$$HOME/.local/bin:$$PATH"' >> ~/.bashrc; \
		export PATH="$$HOME/.local/bin:$$PATH"; \
	else \
		echo ">>> uv already installed: $$(uv --version)"; \
	fi

client-install: ## Install local mnemo CLI dependencies (no Ollama or models)
	@export PATH="$$HOME/.local/bin:$$PATH" && \
	uv sync --all-extras

client-demo: ## Run local demo against MNEMO_OLLAMA_URL
	@export PATH="$$HOME/.local/bin:$$PATH" && \
	MNEMO_OLLAMA_URL="$(MNEMO_OLLAMA_URL)" \
	MNEMO_LLM_MODEL="$(MNEMO_LLM_MODEL)" \
	MNEMO_EMBED_MODEL="$(MNEMO_EMBED_MODEL)" \
	uv run python demo.py

client-test: ## Run local client tests (no Ollama or models)
	@export PATH="$$HOME/.local/bin:$$PATH" && \
	uv run python -m pytest -v

client-lint: ## Run local client linter (no Ollama or models)
	@export PATH="$$HOME/.local/bin:$$PATH" && \
	uv run ruff check src/ tests/

client-scan: ## Run local source-code security scanners
	@export PATH="$$HOME/.local/bin:$$PATH" && \
	uv run mnemo scan

client-redteam: ## Run the authorized local memory-assessment harness
	@export PATH="$$HOME/.local/bin:$$PATH" && \
	MNEMO_OLLAMA_URL="$(MNEMO_OLLAMA_URL)" \
	MNEMO_LLM_MODEL="$(MNEMO_LLM_MODEL)" \
	MNEMO_EMBED_MODEL="$(MNEMO_EMBED_MODEL)" \
	uv run mnemo redteam

client-train: ## Generate dataset, label examples, train the Phase 2 usefulness model
	@export PATH="$$HOME/.local/bin:$$PATH" && \
	MNEMO_OLLAMA_URL="$(MNEMO_OLLAMA_URL)" \
	MNEMO_LLM_MODEL="$(MNEMO_LLM_MODEL)" \
	MNEMO_EMBED_MODEL="$(MNEMO_EMBED_MODEL)" \
	uv run mnemo generate-dataset && \
	MNEMO_OLLAMA_URL="$(MNEMO_OLLAMA_URL)" uv run mnemo label-usefulness && \
	uv run mnemo train-usefulness

client-benchmark: ## Run the Phase 4 ablation benchmark (no-memory / memory-only / +selection)
	@export PATH="$$HOME/.local/bin:$$PATH" && \
	MNEMO_OLLAMA_URL="$(MNEMO_OLLAMA_URL)" \
	MNEMO_LLM_MODEL="$(MNEMO_LLM_MODEL)" \
	MNEMO_EMBED_MODEL="$(MNEMO_EMBED_MODEL)" \
	uv run mnemo benchmark

client-lifecycle: ## Run Phase 3 lifecycle maintenance (decay, dedup, conflicts)
	@export PATH="$$HOME/.local/bin:$$PATH" && uv run mnemo lifecycle

client-security: client-scan client-redteam ## Run local assessment commands

install: client-install ## Alias for client-install
demo: client-demo ## Alias for client-demo
test: client-test ## Alias for client-test
lint: client-lint ## Alias for client-lint
scan: client-scan ## Alias for client-scan
redteam: client-redteam ## Alias for client-redteam
train: client-train ## Alias for client-train
benchmark: client-benchmark ## Alias for client-benchmark
lifecycle: client-lifecycle ## Alias for client-lifecycle
security: client-security ## Alias for client-security

clean: ## Remove database and caches
	rm -rf .venv .pytest_cache __pycache__
	rm -f ~/.local/share/mnemo/memory.db

# --- Remote vLLM coding model (see infra/Makefile) ---------------------------
# Reads VLLM_HOST_URL and VLLM_API_KEY from ./.env (copy .env.example).
opencode: ## Launch OpenCode against the remote vLLM Qwen3-Coder (uses .env)
	@$(MAKE) --no-print-directory -C infra opencode PROJECT_DIR="$(CURDIR)" ENV_FILE="$(CURDIR)/.env"

opencode-config: ## Generate infra/opencode.vllm.json from .env
	@$(MAKE) --no-print-directory -C infra opencode-config PROJECT_DIR="$(CURDIR)" ENV_FILE="$(CURDIR)/.env"
