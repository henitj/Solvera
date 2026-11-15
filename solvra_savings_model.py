"""A transparent, reproducible ML demo for prioritizing savings categories.

Training and evaluation data are generated synthetic profiles. The target is an
explicit heuristic (a hypothetical savings-opportunity score), not observed
human behavior or real-world outcomes. Test accuracy therefore measures how
well the model learns that synthetic rule only.
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import GroupShuffleSplit

CATEGORIES = (
    "Housing",
    "Utilities",
    "Groceries",
    "Transportation",
    "Medical",
    "Dining & Entertainment",
    "Shopping",
    "Subscriptions",
)
DISCRETIONARY = frozenset({"Dining & Entertainment", "Shopping", "Subscriptions"})
SEED = 20261115


def _potential(spend: np.ndarray, category: str, income: float) -> np.ndarray:
    """Synthetic target rule: affordable headroom, weighted toward flexible costs."""
    # Do not treat essential categories as fully reducible. Their simulated
    # headroom is intentionally small; this is a toy prioritization rule only.
    flexible_share = 0.42 if category in DISCRETIONARY else 0.10
    floor = income * (0.035 if category in DISCRETIONARY else 0.10)
    excess = np.maximum(spend - floor, 0.0)
    return excess * flexible_share


def make_synthetic_dataset(n_profiles: int = 4000, seed: int = SEED) -> pd.DataFrame:
    """Create reproducible synthetic monthly budgets and heuristic target labels."""
    if n_profiles < 200:
        raise ValueError("Use at least 200 profiles for a meaningful held-out demo.")
    rng = np.random.default_rng(seed)
    income = np.clip(rng.lognormal(np.log(4200), 0.42, n_profiles), 1200, 18000)
    spending = np.empty((n_profiles, len(CATEGORIES)))
    # Spend proportions vary by profile; modest noise prevents identical rows.
    base = np.array([0.34, 0.08, 0.15, 0.11, 0.06, 0.10, 0.10, 0.06])
    for i in range(n_profiles):
        weights = rng.dirichlet(base * 35)
        spending[i] = income[i] * weights * rng.uniform(0.70, 1.08)
    frame = pd.DataFrame(spending, columns=[f"spend_{c}" for c in CATEGORIES])
    frame.insert(0, "monthly_income", income)
    # Target: category with the largest rule-defined hypothetical headroom.
    scores = np.column_stack(
        [_potential(spending[:, j], category, income) for j, category in enumerate(CATEGORIES)]
    )
    frame["target_category"] = np.asarray(CATEGORIES, dtype=object)[scores.argmax(axis=1)]
    frame["profile_group"] = np.arange(n_profiles)
    return frame


def _feature_columns() -> list[str]:
    return ["monthly_income", *(f"spend_{c}" for c in CATEGORIES)]


@lru_cache(maxsize=1)
def evaluate_model() -> dict:
    """Train on synthetic profiles and evaluate once on profile-disjoint test data."""
    data = make_synthetic_dataset()
    features = _feature_columns()
    data = data.dropna(subset=features + ["target_category"]).copy()
    splitter = GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=SEED)
    train_idx, test_idx = next(
        splitter.split(data[features], data.target_category, groups=data.profile_group)
    )
    model = RandomForestClassifier(
        n_estimators=180, min_samples_leaf=2, class_weight="balanced", random_state=SEED,
        n_jobs=1,
    )
    model.fit(data.iloc[train_idx][features], data.iloc[train_idx].target_category)
    test = data.iloc[test_idx]
    predictions = model.predict(test[features])
    accuracy = float(np.mean(predictions == test.target_category.to_numpy()))
    # The equal-allocation baseline gives every category the same share. Its
    # expected top-choice hit rate under a uniform tie-break is 1 / category count.
    baseline = 1.0 / len(CATEGORIES)
    return {
        "model": model,
        "accuracy": round(accuracy, 4),
        "baseline_accuracy": round(baseline, 4),
        "train_profiles": int(len(train_idx)),
        "test_profiles": int(len(test_idx)),
        "categories": list(CATEGORIES),
        "seed": SEED,
    }


def recommend(monthly_income: float, category_spend: dict[str, float]) -> dict:
    """Predict a category priority and return the underlying demo/profile inputs."""
    income = max(float(monthly_income), 0.0)
    normalized = {c: max(float(category_spend.get(c, 0.0)), 0.0) for c in CATEGORIES}
    row = {"monthly_income": income}
    row.update({f"spend_{c}": normalized[c] for c in CATEGORIES})
    evaluated = evaluate_model()
    model = evaluated["model"]
    X = pd.DataFrame([row], columns=_feature_columns())
    probabilities = model.predict_proba(X)[0]
    ranked = sorted(
        zip(model.classes_, probabilities, strict=True), key=lambda item: item[1], reverse=True
    )
    chosen = str(ranked[0][0])
    potential = float(_potential(np.array([normalized[chosen]]), chosen, income)[0])
    return {
        "category": chosen,
        "confidence": round(float(ranked[0][1]), 3),
        "estimated_monthly_headroom": round(potential, 2),
        "accuracy": evaluated["accuracy"],
        "baseline_accuracy": evaluated["baseline_accuracy"],
        "train_profiles": evaluated["train_profiles"],
        "test_profiles": evaluated["test_profiles"],
        "dataset_note": "Synthetic profiles; target labels come from a stated heuristic.",
    }
