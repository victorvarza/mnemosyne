"""Benchmark + ablation harness.

Runs the memory system end-to-end over a multi-session dataset under several
configurations (ablation study):

| Configuration       | Memory | Usefulness model | Purpose                          |
|---------------------|--------|------------------|----------------------------------|
| no-memory           | OFF    | OFF              | LLM baseline                     |
| memory-only         | ON     | OFF              | raw similarity retrieval         |
| memory+selection    | ON     | ON               | full pipeline (Phase 2 model ON) |
| memory+lifecycle    | ON     | OFF              | conflicts resolved (Phase 3) first |

For each configuration and each QA pair, the system answers with the LLM and
we record QA F1, plus retrieval Recall@k against gold facts (memory configs).

Metrics also include a **bias signal**: the fraction of update-queries answered
with the *stale* (superseded) fact — a direct measure of memory-induced
stale-fact bias, which Phase 4 asks about ("when does memory introduce bias?").

The dataset generator and metrics mirror the style of LoCoMo / LongMemEval
(multi-session QA, Recall@k, F1); `--dataset` accepts any multi-session QA data
converted to the same schema. This is *not* opencode-bench, which scores coding
agents on real commits; see ``bench/opencode-bench/`` for that A/B run.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from mnemo.core.embeddings import EmbeddingModel
from mnemo.core.llm import LLMClient
from mnemo.core.store import MemoryStore
from mnemo.core.types import Memory, MemoryQuery, MemoryType, TrustLevel
from mnemo.eval.dataset import Dataset, f1_score
from mnemo.eval.usefulness import UsefulnessModel
from mnemo.ops.inject import format_memories_block
from mnemo.ops.retrieve import retrieve

CONFIGURATIONS = ["no-memory", "memory-only", "memory+selection", "memory+lifecycle"]

# How long before the questions the session-1 facts were stated. Matches the
# age the Phase 2 labeler assigns to the superseded fact.
SESSION1_AGE_DAYS = 45


@dataclass
class QAResult:
    question: str
    reference: str
    prediction: str
    f1: float
    is_update_query: bool
    answered_with_stale_fact: bool = False
    retrieved_ids: list[str] = field(default_factory=list)


@dataclass
class ConfigReport:
    configuration: str
    n_questions: int
    mean_f1: float
    recall_at_k: float | None  # None for no-memory
    stale_bias_rate: float | None  # fraction of update-queries answered stale
    results: list[QAResult] = field(default_factory=list)


@dataclass
class BenchmarkReport:
    configurations: list[ConfigReport]

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2))
        return path


def _answer(llm: LLMClient, question: str, memory_block: str) -> str:
    prompt = question
    system = "Answer the user's question concisely, in a few words."
    if memory_block:
        system += "\nUse the remembered context below if relevant.\n\n" + memory_block
    return llm.generate(prompt, system=system).strip()


def build_conversation_memories(
    conv, embedder: EmbeddingModel, *, now: datetime | None = None
) -> list[Memory]:
    """Memories for one conversation, timestamped by when they were stated.

    Session-1 facts (including the one later superseded) are dated
    ``SESSION1_AGE_DAYS`` ago; the session-3 update is dated ``now``. This keeps
    the recency feature the usefulness model was trained on meaningful at
    benchmark time: the stale and updated facts no longer look identical.
    Every fact is stated by the user, so trust is USER_STATED throughout.
    """
    now = now or datetime.now(UTC)
    stated_at = [now - timedelta(days=SESSION1_AGE_DAYS)] * len(conv.memories) + [now]
    memories = []
    for fact, ts in zip(conv.memories + [conv.updated_memory], stated_at, strict=True):
        memories.append(
            Memory(
                content=fact,
                memory_type=MemoryType.SEMANTIC,
                trust_level=TrustLevel.USER_STATED,
                source="benchmark",
                embedding=embedder.embed(fact),
                created_at=ts,
                last_accessed=ts,
            )
        )
    return memories


def _run_conversation(
    conv,
    *,
    configuration: str,
    embedder: EmbeddingModel,
    llm: LLMClient,
    usefulness_model: UsefulnessModel | None,
    top_k: int,
    usefulness_threshold: float,
) -> ConfigReport:
    use_memory = configuration != "no-memory"
    use_selection = configuration == "memory+selection" and usefulness_model is not None
    use_lifecycle = configuration == "memory+lifecycle"

    store: MemoryStore | None = None
    gold_ids: dict[str, str] = {}  # fact content -> memory id

    if use_memory:
        store = MemoryStore(":memory:", dimensions=embedder.dimensions)
        for m in build_conversation_memories(conv, embedder):
            store.insert(m)
            gold_ids[m.content] = m.id
        if use_lifecycle:
            # Phase 3 -> Phase 4 interaction: resolve conflicts so the
            # superseded fact is removed before answering.
            from mnemo.lifecycle import run_lifecycle

            run_lifecycle(store, prune_below=None, resolve_conflicts=True)

    results: list[QAResult] = []
    recalls: list[float] = []

    for qa in conv.qa_pairs:
        memory_block = ""
        retrieved_ids: list[str] = []
        if use_memory and store is not None:
            query = MemoryQuery(text=qa.question, top_k=top_k)
            # Route selection through retrieve() so the model sees the real
            # similarity + recency features, not a re-scored approximation.
            retrieved = retrieve(
                store,
                embedder,
                query,
                usefulness_model=usefulness_model if use_selection else None,
                usefulness_threshold=usefulness_threshold,
                touch=False,
            )
            memory_block = format_memories_block(retrieved)
            retrieved_ids = [r.memory.id for r in retrieved]

            gold_id = gold_ids.get(qa.relevant_fact)
            recalls.append(1.0 if gold_id in retrieved_ids else 0.0)

        prediction = _answer(llm, qa.question, memory_block)
        f1 = f1_score(prediction, qa.answer)

        # Stale-bias: an update-query answered with the superseded value.
        answered_stale = bool(
            qa.is_update_query
            and qa.stale_value
            and qa.stale_value.lower() in prediction.lower()
        )

        results.append(
            QAResult(
                question=qa.question,
                reference=qa.answer,
                prediction=prediction,
                f1=f1,
                is_update_query=qa.is_update_query,
                answered_with_stale_fact=answered_stale,
                retrieved_ids=retrieved_ids,
            )
        )

    if store is not None:
        store.close()

    n = max(1, len(results))
    update_results = [r for r in results if r.is_update_query]
    return ConfigReport(
        configuration=configuration,
        n_questions=len(results),
        mean_f1=sum(r.f1 for r in results) / n,
        recall_at_k=(sum(recalls) / max(1, len(recalls))) if use_memory else None,
        stale_bias_rate=(
            sum(1 for r in update_results if r.answered_with_stale_fact)
            / max(1, len(update_results))
        )
        if use_memory
        else None,
        results=results,
    )


def run_benchmark(
    dataset: Dataset,
    embedder: EmbeddingModel,
    llm: LLMClient,
    *,
    usefulness_model: UsefulnessModel | None = None,
    configurations: list[str] | None = None,
    top_k: int = 5,
    usefulness_threshold: float = 0.5,
) -> BenchmarkReport:
    """Run the ablation benchmark over all conversations and configurations."""
    configurations = configurations or CONFIGURATIONS
    reports: list[ConfigReport] = []
    for config in configurations:
        if config == "memory+selection" and usefulness_model is None:
            # Skip gracefully: the selection config needs a trained model.
            continue
        per_conv = [
            _run_conversation(
                conv,
                configuration=config,
                embedder=embedder,
                llm=llm,
                usefulness_model=usefulness_model,
                top_k=top_k,
                usefulness_threshold=usefulness_threshold,
            )
            for conv in dataset.conversations
        ]
        # Aggregate across conversations.
        all_results = [r for c in per_conv for r in c.results]
        n = max(1, len(all_results))
        update_results = [r for r in all_results if r.is_update_query]
        recalls = [c.recall_at_k for c in per_conv if c.recall_at_k is not None]
        reports.append(
            ConfigReport(
                configuration=config,
                n_questions=len(all_results),
                mean_f1=sum(r.f1 for r in all_results) / n,
                recall_at_k=(sum(recalls) / max(1, len(recalls))) if recalls else None,
                stale_bias_rate=(
                    sum(1 for r in update_results if r.answered_with_stale_fact)
                    / max(1, len(update_results))
                )
                if update_results and config != "no-memory"
                else None,
                results=all_results,
            )
        )
    return BenchmarkReport(configurations=reports)


def format_report(report: BenchmarkReport) -> str:
    """Render a compact markdown table of the ablation results."""
    lines = [
        "| Configuration | Questions | Mean F1 | Recall@k | Stale-bias rate |",
        "|---|---|---|---|---|",
    ]
    for c in report.configurations:
        recall = f"{c.recall_at_k:.2f}" if c.recall_at_k is not None else "—"
        bias = f"{c.stale_bias_rate:.2f}" if c.stale_bias_rate is not None else "—"
        lines.append(f"| {c.configuration} | {c.n_questions} | {c.mean_f1:.3f} | {recall} | {bias} |")
    return "\n".join(lines)
