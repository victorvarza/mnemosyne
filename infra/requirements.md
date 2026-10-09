# Coding-model serving — instance & model sizing

Reference for picking an open-source coding model and the AWS GPU instance to
serve it on with vLLM, feeding the OpenCode CLI (see `infra/Makefile` and the
`VLLM_HOST_URL` wiring).

## Sizing rule of thumb (vLLM serving)

Weights ≈ **2 GB/B** at BF16, **~1 GB/B** at FP8, **~0.5 GB/B** at 4-bit
(AWQ/GPTQ). Then leave **20–40% of VRAM free for KV cache** — more for long
context or high concurrency. In short: weights should use **≲70% of aggregate
VRAM**.

## Instances (GPU only)

| Instance | Accelerators | Aggregate VRAM | Host RAM |
|---|---|---|---|
| `g5.12xlarge` | 4× A10G 24 GB | 96 GB | 192 GB |
| `p4d.24xlarge` | 8× A100 40 GB | 320 GB | 1.1 TB |
| `p4de.24xlarge` | 8× A100 80 GB | 640 GB | 1.1 TB |
| `p5.48xlarge` | 8× H100 80 GB | 640 GB (FP8-native, ~2–3× faster) | 2 TB |
| `p5en.48xlarge` | 8× H200 141 GB | 1,128 GB | 2 TB |

## Best coding model per instance

| Instance | Top pick (coding) | Precision / fit | Also good |
|---|---|---|---|
| `g5.12xlarge` (96 GB) | **Qwen2.5-Coder-32B** | AWQ/FP8 ≈ 20–32 GB, lots of KV room | Qwen3-Coder-30B-A3B; Llama-3.3-70B AWQ (~40 GB) |
| `p4d.24xlarge` (320 GB) | **Qwen2.5-Coder-32B BF16** (~64 GB) | huge KV headroom, long context, high concurrency | Llama-3.3-70B BF16 (~140 GB); DeepSeek-Coder-V2 236B 4-bit (~130 GB) |
| `p4de.24xlarge` (640 GB) | **Qwen3-Coder-480B-A35B** | 4-bit ≈ 250 GB | DeepSeek-V3.1 4-bit (~380 GB); GLM-4.5 355B FP8 |
| `p5.48xlarge` (640 GB, H100) | **Qwen3-Coder-480B-A35B FP8** (~480 GB) | FP8-native, fast | DeepSeek-V3.1 (tight at FP8 — run 4-bit or trim context) |
| `p5en.48xlarge` (1,128 GB, H200) | **DeepSeek-V3.1 671B FP8** (~670 GB) or **Qwen3-Coder-480B FP8** w/ big context | room for long context + concurrency | Kimi K2 (1T-A32B) FP8; GLM-4.6 355B BF16 |

## How to choose

- **Best quality-per-dollar coding agent:** Qwen2.5-Coder-32B on `g5.12xlarge`
  or `p4d` — near the top of open coding benchmarks, Apache-2.0, modest VRAM.
  The sweet spot for an always-on worker.
- **MoE efficiency (high throughput, low active params):** Qwen3-Coder-30B-A3B
  — excellent on `g5`.
- **Frontier-class open coding, GPUs available:** Qwen3-Coder-480B-A35B
  (`p4de`/`p5`) or DeepSeek-V3.1 (`p5en`). Qwen3-Coder is purpose-built for
  coding/agents; DeepSeek-V3.1 is the stronger generalist-reasoner.

## License notes

- **Apache-2.0 (cleanest):** Qwen2.5-Coder, Qwen3-Coder, DeepSeek-Coder-V2.
- **MIT-ish:** DeepSeek-V3/V3.1, GLM-4.5/4.6.
- **Community license (restrictions/attribution):** Llama 3.3.
- **Avoid for production unless terms are checked:** Codestral 22B (Mistral
  non-production license).

## Fit for this project

`infra/Makefile` launches OpenCode against a remote vLLM Qwen3-Coder worker:

- **Coding worker:** `g5.12xlarge` running Qwen2.5-Coder-32B (or
  Qwen3-Coder-30B-A3B) via vLLM — matches the existing `VLLM_HOST_URL` wiring
  and is cost-sane for an always-on service.
- Scale to `p4de`/`p5` with Qwen3-Coder-480B only when frontier quality is
  needed (e.g. opencode-bench runs).
- Keep embeddings (`nomic-embed-text`) cheap and on a separate worker — they
  don't need any of these instances.
