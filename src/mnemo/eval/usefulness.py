"""Learned usefulness model for memory selection.

Trains a logistic-regression classifier that predicts whether a retrieved
memory will be *helpful* for a given query, from features of the
(query, memory) pair:

- embedding similarity (``1 - L2 distance`` from sqlite-vec; ranks like cosine
  for unit-length embeddings)
- memory recency score (exponential decay of time since last access)
- trust level (user_stated / agent_inferred / external_document / unknown)

Decay score, access count, and memory type can still be computed
(``ALL_FEATURE_NAMES``) but are not trained on; see ``FEATURE_NAMES``.

Training data is (query, memory, helpful) triples. Currently labels come from
the deterministic synthetic labeler (``mnemo label-usefulness``); logged
downstream usage (e.g. the memory was actually cited in a response) is the
intended source for real data.

The trained parameters are pure Python (a weight vector + feature spec) stored
as JSON, so inference has no dependency on scikit-learn; training uses
scikit-learn when available and falls back to a small built-in gradient-descent
logistic regression otherwise.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

from mnemo.core.types import Memory, MemoryType, TrustLevel

ALL_FEATURE_NAMES = [
    "similarity",
    "recency",
    "decay_score",
    "log_access_count",
    "type_episodic",
    "type_procedural",
    "trust_user_stated",
    "trust_agent_inferred",
    "trust_external_document",
]

# Features new models are trained on: the ones the labeler makes informative.
# Access count and memory type are random in the synthetic data, so the model
# could only fit noise on them, and access count grows with every retrieval at
# serve time: a negative weight would suppress a memory after a few uses.
FEATURE_NAMES = [
    "similarity",
    "recency",
    "trust_user_stated",
    "trust_agent_inferred",
    "trust_external_document",
]


def default_model_path() -> Path:
    """Default usefulness-model path (overridable via MNEMO_USEFULNESS_MODEL)."""
    import os

    override = os.getenv("MNEMO_USEFULNESS_MODEL")
    if override:
        return Path(override)
    return Path.home() / ".local" / "share" / "mnemo" / "usefulness-model.json"


@dataclass
class UsefulnessExample:
    """One labeled (query, memory) training example."""

    query: str
    memory_content: str
    helpful: bool
    similarity: float
    recency: float
    decay_score: float = 1.0
    access_count: int = 0
    memory_type: str = MemoryType.SEMANTIC.value
    trust_level: str = TrustLevel.UNKNOWN.value


@dataclass
class UsefulnessModel:
    """A trained logistic-regression usefulness classifier."""

    weights: list[float]
    bias: float
    feature_names: list[str]
    trained_on: int = 0
    positive_rate: float = 0.5

    @staticmethod
    def featurize(
        *,
        similarity: float,
        recency: float,
        memory: Memory | None = None,
        decay_score: float = 1.0,
        access_count: int = 0,
        memory_type: str = MemoryType.SEMANTIC.value,
        trust_level: str = TrustLevel.UNKNOWN.value,
        feature_names: list[str] | None = None,
    ) -> list[float]:
        """Feature vector in ``feature_names`` order (default: ``FEATURE_NAMES``)."""
        if memory is not None:
            decay_score = memory.decay_score
            access_count = memory.access_count
            memory_type = memory.memory_type.value
            trust_level = memory.trust_level.value
        values = {
            "similarity": similarity,
            "recency": recency,
            "decay_score": decay_score,
            "log_access_count": math.log1p(max(0, access_count)),
            "type_episodic": 1.0 if memory_type == MemoryType.EPISODIC.value else 0.0,
            "type_procedural": 1.0 if memory_type == MemoryType.PROCEDURAL.value else 0.0,
            "trust_user_stated": 1.0 if trust_level == TrustLevel.USER_STATED.value else 0.0,
            "trust_agent_inferred": 1.0 if trust_level == TrustLevel.AGENT_INFERRED.value else 0.0,
            "trust_external_document": (
                1.0 if trust_level == TrustLevel.EXTERNAL_DOCUMENT.value else 0.0
            ),
        }
        return [values[name] for name in (feature_names or FEATURE_NAMES)]

    def score(
        self,
        *,
        similarity: float,
        recency: float,
        memory: Memory | None = None,
        **kwargs,
    ) -> float:
        """Probability that this (query, memory) pair is helpful, in [0, 1]."""
        # Score with the features this model was trained on, so models saved
        # with an older feature set keep working.
        x = self.featurize(
            similarity=similarity,
            recency=recency,
            memory=memory,
            feature_names=self.feature_names,
            **kwargs,
        )
        z = self.bias + sum(w * xi for w, xi in zip(self.weights, x, strict=True))
        # Numerically stable sigmoid.
        if z >= 0:
            return 1.0 / (1.0 + math.exp(-z))
        ez = math.exp(z)
        return ez / (1.0 + ez)

    def save(self, path: str | Path | None = None) -> Path:
        path = Path(path) if path else default_model_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2))
        return path

    @classmethod
    def load(cls, path: str | Path | None = None) -> UsefulnessModel:
        path = Path(path) if path else default_model_path()
        data = json.loads(path.read_text())
        data.pop("DEFAULT_PATH", None)
        return cls(**data)

    @classmethod
    def load_or_none(cls, path: str | Path | None = None) -> UsefulnessModel | None:
        path = Path(path) if path else default_model_path()
        if not path.exists():
            return None
        return cls.load(path)


def _standardize(features: list[list[float]]) -> tuple[list[list[float]], list[float], list[float]]:
    n_features = len(features[0])
    means = [0.0] * n_features
    stds = [1.0] * n_features
    n = len(features)
    for j in range(n_features):
        col = [row[j] for row in features]
        means[j] = sum(col) / n
        var = sum((v - means[j]) ** 2 for v in col) / n
        stds[j] = math.sqrt(var) if var > 1e-12 else 1.0
    scaled = [
        [(row[j] - means[j]) / stds[j] for j in range(n_features)] for row in features
    ]
    return scaled, means, stds


def _train_builtin(
    features: list[list[float]],
    labels: list[bool],
    *,
    epochs: int = 800,
    lr: float = 0.5,
    l2: float = 1e-3,
) -> tuple[list[float], float]:
    """Small gradient-descent logistic regression (no external deps).

    Uses class-balanced weighting so imbalanced datasets (few helpful examples)
    still train a useful decision boundary.
    """
    n = len(features)
    n_features = len(features[0])
    weights = [0.0] * n_features
    bias = 0.0
    ys = [1.0 if y else 0.0 for y in labels]
    n_pos = max(1, sum(ys))
    n_neg = max(1, n - n_pos)
    w_pos = n / (2.0 * n_pos)
    w_neg = n / (2.0 * n_neg)

    for _ in range(epochs):
        grad_w = [0.0] * n_features
        grad_b = 0.0
        for x, y in zip(features, ys, strict=True):
            z = bias + sum(w * xi for w, xi in zip(weights, x, strict=True))
            p = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))
            err = (p - y) * (w_pos if y > 0.5 else w_neg)
            for j in range(n_features):
                grad_w[j] += err * x[j]
            grad_b += err
        for j in range(n_features):
            weights[j] -= lr * (grad_w[j] / n + l2 * weights[j])
        bias -= lr * grad_b / n
    return weights, bias


def train_usefulness_model(
    examples: list[UsefulnessExample],
) -> UsefulnessModel:
    """Train the usefulness classifier from labeled examples.

    Uses scikit-learn when installed; otherwise falls back to the built-in
    gradient-descent implementation. Returns an unstandardized model whose
    weights operate directly on raw features (standardization folded back in).
    """
    if len(examples) < 4:
        raise ValueError(
            f"Need at least 4 labeled examples to train, got {len(examples)}"
        )

    raw = [
        UsefulnessModel.featurize(
            similarity=e.similarity,
            recency=e.recency,
            decay_score=e.decay_score,
            access_count=e.access_count,
            memory_type=e.memory_type,
            trust_level=e.trust_level,
        )
        for e in examples
    ]
    labels = [e.helpful for e in examples]
    positive_rate = sum(labels) / len(labels)

    scaled, means, stds = _standardize(raw)

    try:
        from sklearn.linear_model import LogisticRegression

        clf = LogisticRegression(max_iter=1000, class_weight="balanced")
        clf.fit(scaled, [1 if y else 0 for y in labels])
        weights_scaled = list(clf.coef_[0])
        bias_scaled = float(clf.intercept_[0])
    except ImportError:
        weights_scaled, bias_scaled = _train_builtin(scaled, labels)

    # Fold standardization back into raw-feature space so inference needs no
    # stored scaler state.
    weights_raw = [w / s for w, s in zip(weights_scaled, stds, strict=True)]
    bias_raw = bias_scaled - sum(
        w * m / s for w, m, s in zip(weights_scaled, means, stds, strict=True)
    )

    return UsefulnessModel(
        weights=weights_raw,
        bias=bias_raw,
        feature_names=list(FEATURE_NAMES),
        trained_on=len(examples),
        positive_rate=positive_rate,
    )


def evaluate_usefulness_model(
    model: UsefulnessModel, examples: list[UsefulnessExample]
) -> dict[str, float]:
    """Accuracy / precision / recall / F1 of the model on held-out examples."""
    tp = fp = tn = fn = 0
    for e in examples:
        p = model.score(
            similarity=e.similarity,
            recency=e.recency,
            decay_score=e.decay_score,
            access_count=e.access_count,
            memory_type=e.memory_type,
            trust_level=e.trust_level,
        )
        predicted = p >= 0.5
        if predicted and e.helpful:
            tp += 1
        elif predicted and not e.helpful:
            fp += 1
        elif not predicted and e.helpful:
            fn += 1
        else:
            tn += 1
    total = max(1, tp + fp + tn + fn)
    precision = tp / max(1, tp + fp)
    recall = tp / max(1, tp + fn)
    f1 = 2 * precision * recall / max(1e-9, precision + recall)
    return {
        "accuracy": (tp + tn) / total,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "n": float(total),
    }
