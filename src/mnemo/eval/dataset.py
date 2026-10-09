"""Synthetic multi-session conversation generator + labeling (Phases 2 & 4).

Generates LoCoMo-style multi-session conversations with a fixed persona:
facts are established in early sessions and queried later, plus distractor
topics and one fact *update* (to exercise conflict handling).

Usage:
    mnemo generate-dataset --out data/sample_conversations/dataset.json
    mnemo label-usefulness --dataset data/sample_conversations/dataset.json
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from mnemo.core.embeddings import EmbeddingModel
from mnemo.core.store import MemoryStore
from mnemo.core.types import Memory, MemoryType, TrustLevel
from mnemo.eval.usefulness import UsefulnessExample
from mnemo.ops.retrieve import _recency_score

PERSONAS = [
    {
        "name": "user",
        "facts": [
            ("language", "Python", ["Java", "TypeScript", "Go"]),
            ("editor", "Neovim", ["VS Code", "Emacs", "JetBrains"]),
            ("os", "macOS", ["Ubuntu", "Fedora", "Windows"]),
            ("database", "PostgreSQL", ["MySQL", "SQLite", "MongoDB"]),
            ("cloud", "AWS", ["GCP", "Azure", "on-prem"]),
            ("test_framework", "pytest", ["unittest", "nose", "Jest"]),
            ("city", "Bucharest", ["Cluj", "Berlin", "Amsterdam"]),
            ("team", "Gemini Platform", ["Sensei", "Express", "AEM"]),
        ],
        "distractors": [
            "Let's discuss the weather this weekend.",
            "Can you explain how TCP slow start works?",
            "What's a good recipe for pancakes?",
            "Help me understand the CAP theorem.",
            "Write a haiku about deadlines.",
        ],
    }
]


@dataclass
class QAPair:
    question: str
    answer: str
    relevant_fact: str
    is_update_query: bool = False
    stale_value: str = ""  # superseded value for update queries (for bias metric)


@dataclass
class Conversation:
    """One multi-session conversation: memories established + later queries."""

    sessions: list[list[str]]
    memories: list[str]  # facts extractable from session 1
    updated_memory: str  # the fact after it changes (conflict case)
    stale_value: str = ""  # the value the updated memory supersedes
    updated_value: str = ""  # the new value after the update
    qa_pairs: list[QAPair] = field(default_factory=list)


@dataclass
class Dataset:
    conversations: list[Conversation]

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2))
        return path

    @classmethod
    def load(cls, path: str | Path) -> Dataset:
        data = json.loads(Path(path).read_text())
        convs = []
        for c in data["conversations"]:
            c["qa_pairs"] = [QAPair(**qa) for qa in c.get("qa_pairs", [])]
            convs.append(Conversation(**c))
        return cls(conversations=convs)


def _fact_sentence(key: str, value: str) -> str:
    templates = {
        "language": f"My preferred programming language is {value}.",
        "editor": f"I use {value} as my editor.",
        "os": f"My machine runs {value}.",
        "database": f"Our production database is {value}.",
        "cloud": f"We deploy on {value}.",
        "test_framework": f"For tests I always use {value}.",
        "city": f"I live in {value}.",
        "team": f"I work on the {value} team.",
    }
    return templates.get(key, f"My {key} is {value}.")


def generate_conversation(persona: dict | None = None, seed: int = 42) -> Conversation:
    """Build one synthetic multi-session conversation with known ground truth."""
    rng = random.Random(seed)
    persona = persona or PERSONAS[0]
    facts = persona["facts"]
    update_key_idx = rng.randrange(len(facts))
    update_key, update_old, update_alts = facts[update_key_idx]
    update_new = rng.choice(update_alts)

    memories = [_fact_sentence(k, v) for k, v, _ in facts]
    updated_memory = _fact_sentence(update_key, update_new)

    # Session 1: establish all facts.
    session1 = ["Hi, let's set up my profile."] + memories
    # Session 2: distractor chatter.
    session2 = rng.sample(persona["distractors"], k=min(3, len(persona["distractors"])))
    # Session 3: the user changes one fact (conflict/staleness case).
    session3 = [
        f"Quick update — I've changed things: {updated_memory}",
        "Please use that from now on.",
    ]
    # Session 4: questions about the facts (some about the updated one).
    qa_pairs = []
    session4 = []
    for i, (key, value, _) in enumerate(facts):
        is_updated = i == update_key_idx
        answer = update_new if is_updated else value
        q_templates = {
            "language": "Which programming language do I prefer?",
            "editor": "Which editor do I use?",
            "os": "Which OS does my machine run?",
            "database": "What is our production database?",
            "cloud": "Which cloud do we deploy on?",
            "test_framework": "Which test framework do I use?",
            "city": "Which city do I live in?",
            "team": "Which team do I work on?",
        }
        question = q_templates.get(key, f"What is my {key}?")
        session4.append(question)
        qa_pairs.append(
            QAPair(
                question=question,
                answer=answer,
                relevant_fact=_fact_sentence(key, answer),
                is_update_query=is_updated,
                stale_value=update_old if is_updated else "",
            )
        )

    return Conversation(
        sessions=[session1, session2, session3, session4],
        memories=memories,
        updated_memory=updated_memory,
        stale_value=update_old,
        updated_value=update_new,
        qa_pairs=qa_pairs,
    )


def generate_dataset(n_conversations: int = 10, seed: int = 42) -> Dataset:
    return Dataset(
        conversations=[
            generate_conversation(seed=seed + i) for i in range(n_conversations)
        ]
    )


def label_usefulness_examples(
    dataset: Dataset,
    embedder: EmbeddingModel,
    *,
    top_k: int = 5,
    negative_ratio: float = 1.0,
    seed: int = 42,
) -> list[UsefulnessExample]:
    """Build labeled (query, memory, helpful) examples from the dataset.

    For every QA pair, retrieves the top-k memories and labels each by
    ground truth (does the memory contain the gold answer?), adjusted by the
    feature-correlated rules below. Labeling is deterministic; no LLM is used.

    Also samples random (distractor-query, memory) pairs as negatives to
    balance the dataset.
    """
    rng = random.Random(seed)
    examples: list[UsefulnessExample] = []

    # Feature pools for the Phase 2 model. To keep the synthetic data
    # reproducible and the labels *learnable*, features are sampled
    # deterministically per question and *correlated with helpfulness*:
    # - agent_inferred memories are wrong (unhelpful) with probability
    #   ``agent_inferred_error_rate``;
    # - the stale (superseded) fact is old and always unhelpful for the
    #   update query.
    type_pool = [MemoryType.SEMANTIC, MemoryType.SEMANTIC, MemoryType.EPISODIC, MemoryType.PROCEDURAL]
    trust_pool = [
        TrustLevel.USER_STATED,
        TrustLevel.USER_STATED,
        TrustLevel.AGENT_INFERRED,
        TrustLevel.EXTERNAL_DOCUMENT,
    ]
    agent_inferred_error_rate = 0.6
    now = datetime.now(UTC)

    for conv in dataset.conversations:
        store = MemoryStore(":memory:", dimensions=embedder.dimensions)
        all_facts = conv.memories + [conv.updated_memory]
        stored: list[Memory] = []
        for fact in all_facts:
            age_days = rng.choice([0, 2, 7, 20, 45])
            m = Memory(
                content=fact,
                memory_type=rng.choice(type_pool),
                trust_level=rng.choice(trust_pool),
                source="dataset",
                embedding=embedder.embed(fact),
                access_count=rng.choice([0, 0, 1, 3, 8]),
                last_accessed=now - timedelta(days=age_days),
            )
            store.insert(m)
            stored.append(m)
        stale_memory = next(
            (m for m in stored if conv.stale_value and conv.stale_value in m.content),
            None,
        )

        for qa in conv.qa_pairs:
            # Deterministic per-question features: re-running the labeler on the
            # same dataset reproduces the same examples.
            q_rng = random.Random(f"{seed}:{qa.question}")
            query_embedding = embedder.embed(qa.question)
            results = store.search(query_embedding, top_k=top_k)
            for memory, similarity in results:
                memory_type = q_rng.choice(type_pool)
                trust_level = q_rng.choice(trust_pool)
                age_days = q_rng.choice([0, 2, 7, 20, 45])

                # Ground truth: does this memory contain the gold answer?
                helpful = qa.answer.lower() in memory.content.lower()

                # Label-correlated feature: agent_inferred memories are wrong
                # with some probability (they hallucinate plausible-but-false
                # facts), so trust carries real signal.
                if (
                    helpful
                    and trust_level == TrustLevel.AGENT_INFERRED
                    and q_rng.random() < agent_inferred_error_rate
                ):
                    helpful = False

                # Label-correlated features: the stale fact is old and always
                # unhelpful for the update query.
                if stale_memory is not None and memory.id == stale_memory.id:
                    age_days = 45
                    if qa.is_update_query:
                        helpful = False

                example_memory = Memory(
                    content=memory.content,
                    memory_type=memory_type,
                    trust_level=trust_level,
                    source="dataset",
                    access_count=q_rng.choice([0, 0, 1, 3, 8]),
                    last_accessed=now - timedelta(days=age_days),
                )
                examples.append(
                    UsefulnessExample(
                        query=qa.question,
                        memory_content=memory.content,
                        helpful=helpful,
                        similarity=similarity,
                        recency=_recency_score(example_memory),
                        decay_score=example_memory.decay_score,
                        access_count=example_memory.access_count,
                        memory_type=memory_type.value,
                        trust_level=trust_level.value,
                    )
                )

        # Negatives: distractor queries paired with random facts. The
        # similarity is the *real* store similarity between the distractor query and the
        # memory, so the model learns "low similarity => not helpful" instead of
        # fitting fabricated numbers that overlap the positives.
        n_negatives = int(len(examples) * negative_ratio) or 1
        distractor_queries = ["What's the weather?", "Tell me a joke.", "Explain recursion."]
        distractor_embeddings = {q: embedder.embed(q) for q in distractor_queries}
        for _ in range(min(n_negatives, len(stored) * len(distractor_queries))):
            memory = rng.choice(stored)
            query = rng.choice(distractor_queries)
            real_similarity = next(
                (score for m, score in store.search(distractor_embeddings[query], top_k=len(stored)) if m.id == memory.id),
                0.0,
            )
            examples.append(
                UsefulnessExample(
                    query=query,
                    memory_content=memory.content,
                    helpful=False,
                    similarity=real_similarity,
                    recency=_recency_score(memory),
                    decay_score=memory.decay_score,
                    access_count=memory.access_count,
                    memory_type=memory.memory_type.value,
                    trust_level=memory.trust_level.value,
                )
            )
        store.close()

    rng.shuffle(examples)
    return examples


def save_examples(examples: list[UsefulnessExample], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(e) for e in examples], indent=2))
    return path


def load_examples(path: str | Path) -> list[UsefulnessExample]:
    return [UsefulnessExample(**e) for e in json.loads(Path(path).read_text())]


# Word-token overlap for extractive QA scoring.
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def f1_score(prediction: str, reference: str) -> float:
    """Token-level F1 between prediction and reference (SQuAD-style)."""
    pred_tokens = _TOKEN_RE.findall(prediction.lower())
    ref_tokens = _TOKEN_RE.findall(reference.lower())
    if not pred_tokens or not ref_tokens:
        return 0.0
    common = 0
    ref_counts: dict[str, int] = {}
    for t in ref_tokens:
        ref_counts[t] = ref_counts.get(t, 0) + 1
    for t in pred_tokens:
        if ref_counts.get(t, 0) > 0:
            common += 1
            ref_counts[t] -= 1
    if common == 0:
        return 0.0
    precision = common / len(pred_tokens)
    recall = common / len(ref_tokens)
    return 2 * precision * recall / (precision + recall)
