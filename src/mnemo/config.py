"""Configuration defaults shared by the local client."""

from __future__ import annotations

import os

MNEMO_OLLAMA_URL = "MNEMO_OLLAMA_URL"
MNEMO_LLM_MODEL = "MNEMO_LLM_MODEL"
MNEMO_EMBED_MODEL = "MNEMO_EMBED_MODEL"

DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_LLM_MODEL = "qwen2.5:7b"
DEFAULT_EMBED_MODEL = "nomic-embed-text"


def ollama_url() -> str:
    return os.getenv(MNEMO_OLLAMA_URL, DEFAULT_OLLAMA_URL)


def llm_model() -> str:
    return os.getenv(MNEMO_LLM_MODEL, DEFAULT_LLM_MODEL)


def embed_model() -> str:
    return os.getenv(MNEMO_EMBED_MODEL, DEFAULT_EMBED_MODEL)
