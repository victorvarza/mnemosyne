from __future__ import annotations

import httpx

from mnemo.config import llm_model as default_llm_model
from mnemo.config import ollama_url as default_ollama_url


class LLMClient:
    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float = 120.0,
    ):
        self.model = default_llm_model() if model is None else model
        self.base_url = default_ollama_url() if base_url is None else base_url
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout)

    def generate(self, prompt: str, *, system: str = "") -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return self.chat(messages)

    def chat(self, messages: list[dict[str, str]]) -> str:
        response = self._client.post(
            "/api/chat",
            json={
                "model": self.model,
                "messages": messages,
                "stream": False,
                # Deterministic decoding: benchmark/eval numbers must be
                # comparable run-to-run (F1 deltas otherwise drown in noise).
                "options": {"temperature": 0},
            },
        )
        response.raise_for_status()
        return response.json()["message"]["content"]

    def is_available(self) -> bool:
        try:
            resp = self._client.get("/api/tags")
            return resp.status_code == 200
        except httpx.HTTPError:
            return False

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
