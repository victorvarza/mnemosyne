from __future__ import annotations

import httpx

from mnemo.config import embed_model as default_embed_model
from mnemo.config import ollama_url as default_ollama_url


class EmbeddingModel:
    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float = 60.0,
    ):
        self.model = default_embed_model() if model is None else model
        self.base_url = default_ollama_url() if base_url is None else base_url
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout)
        self._dimensions: int | None = None

    @property
    def dimensions(self) -> int:
        if self._dimensions is None:
            test = self.embed("test")
            self._dimensions = len(test)
        return self._dimensions

    def embed(self, text: str) -> list[float]:
        response = self._client.post(
            "/api/embed",
            json={"model": self.model, "input": text},
        )
        response.raise_for_status()
        return response.json()["embeddings"][0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = self._client.post(
            "/api/embed",
            json={"model": self.model, "input": texts},
        )
        response.raise_for_status()
        return response.json()["embeddings"]

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
