"""Mnemosyne demo — stores sample memories, then retrieves them by semantic search."""

from mnemo.core.embeddings import EmbeddingModel
from mnemo.core.llm import LLMClient
from mnemo.core.store import MemoryStore
from mnemo.core.types import Memory, MemoryQuery, MemoryType, TrustLevel
from mnemo.ops.inject import format_memories_block
from mnemo.ops.retrieve import retrieve

SAMPLE_MEMORIES = [
    ("User prefers Python over Java for backend services", MemoryType.SEMANTIC, TrustLevel.USER_STATED),
    ("User is allergic to shellfish", MemoryType.SEMANTIC, TrustLevel.USER_STATED),
    ("On 2024-09-03 user debugged a tricky SQLite locking issue", MemoryType.EPISODIC, TrustLevel.AGENT_INFERRED),
    ("Always use type hints in function signatures", MemoryType.PROCEDURAL, TrustLevel.USER_STATED),
    ("User works at Google on the Workspace Platform team", MemoryType.SEMANTIC, TrustLevel.USER_STATED),
    ("When writing tests, prefer pytest fixtures over setUp/tearDown", MemoryType.PROCEDURAL, TrustLevel.AGENT_INFERRED),
    ("User is reskilling from platform engineering into ML engineering", MemoryType.SEMANTIC, TrustLevel.USER_STATED),
]

DEMO_QUERIES = [
    "What programming language does the user prefer?",
    "What should I know about writing tests for this user?",
    "What does the user do for work?",
]


def main():
    print("=" * 60)
    print("  Mnemosyne — Personalized Context Memory Demo")
    print("=" * 60)

    print("\n>>> Connecting to Ollama...")
    embedder = EmbeddingModel()
    if not embedder.is_available():
        print("ERROR: Ollama is not running. Start it with: ollama serve")
        return

    llm = LLMClient()
    dims = embedder.dimensions
    store = MemoryStore(dimensions=dims)

    print(f">>> Embedding model ready (dimensions={dims})")
    print(f">>> LLM model: {llm.model}")

    print(f"\n>>> Storing {len(SAMPLE_MEMORIES)} sample memories...")
    for content, mtype, trust in SAMPLE_MEMORIES:
        embedding = embedder.embed(content)
        memory = Memory(
            content=content,
            memory_type=mtype,
            trust_level=trust,
            source="demo",
            embedding=embedding,
        )
        store.insert(memory)
        print(f"    [{mtype.value}] {content}")

    print(f"\n>>> Store contains {store.count()} memories")

    for query_text in DEMO_QUERIES:
        print(f"\n{'─' * 60}")
        print(f"  Query: {query_text}")
        print(f"{'─' * 60}")

        query = MemoryQuery(text=query_text, top_k=3, recency_weight=0.1)
        results = retrieve(store, embedder, query)

        for r in results:
            m = r.memory
            print(f"  [{r.score:.3f}] ({m.memory_type.value}|{m.trust_level.value}) {m.content}")

        memory_block = format_memories_block(results)
        print(f"\n  Injected context block:\n{memory_block}")

        print(f"\n  >>> Asking LLM with memory context...")
        system_prompt = (
            "You are a helpful assistant. Use the remembered context below to personalize your answer.\n\n"
            + memory_block
        )
        answer = llm.generate(query_text, system=system_prompt)
        print(f"  LLM: {answer}")

    store.close()
    embedder.close()
    llm.close()
    print(f"\n{'=' * 60}")
    print("  Demo complete.")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
