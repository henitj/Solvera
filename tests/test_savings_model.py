import solvra_savings_model as model


def test_synthetic_dataset_reproducible_and_profile_disjoint():
    a = model.make_synthetic_dataset(300, seed=10)
    b = model.make_synthetic_dataset(300, seed=10)
    assert a.equals(b)
    assert a.profile_group.nunique() == 300
    assert set(a.target_category).issubset(model.CATEGORIES)


def test_heldout_model_beats_uniform_category_baseline():
    result = model.evaluate_model()
    assert result["test_profiles"] > 0
    assert result["train_profiles"] + result["test_profiles"] == 4000
    assert result["accuracy"] > result["baseline_accuracy"]


def test_recommendation_is_bounded_and_discloses_synthetic_data():
    result = model.recommend(
        4000,
        {
            "Dining & Entertainment": 900,
            "Housing": 1400,
            "Groceries": 600,
        },
    )
    assert result["category"] in model.CATEGORIES
    assert result["estimated_monthly_headroom"] >= 0
    assert "Synthetic" in result["dataset_note"]
