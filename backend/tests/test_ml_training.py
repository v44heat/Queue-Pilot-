import joblib
import numpy as np
import pandas as pd
import pytest

from app.ml import training
from app.ml.dataset import DatasetError, clean_dataset
from app.ml.features import FEATURE_COLUMNS, NUMERIC_ALL, TARGET, FeatureBuilder
from app.ml.synthetic import generate_dataset
from app.ml.training import (
    TrainedModel, chronological_split, compute_metrics, load_model, predict_minutes, save_model,
    select_best, train_and_compare,
)

pytestmark = pytest.mark.usefixtures("fast_models")


@pytest.fixture(scope="module")
def frame():
    df, _ = clean_dataset(generate_dataset(3000, 11))
    return df


@pytest.fixture(scope="module")
def result(frame):
    import app.ml.training as t
    old = (dict(t.RF_PARAMS), dict(t.GB_PARAMS))
    t.RF_PARAMS["n_estimators"], t.GB_PARAMS["n_estimators"] = 20, 40
    try:
        return train_and_compare(frame, seed=11)
    finally:
        t.RF_PARAMS.update(old[0]); t.GB_PARAMS.update(old[1])


# ---------------------------------------------------------------- metrics
def test_metrics_match_hand_calculation():
    m = compute_metrics([1, 2, 3], [1, 2, 5])
    assert m["mae"] == pytest.approx(0.6667, abs=1e-4)
    assert m["rmse"] == pytest.approx(np.sqrt(4 / 3), abs=1e-4)
    assert m["r2"] == pytest.approx(-1.0)
    assert compute_metrics([2, 4], [2, 4]) == {"mae": 0.0, "rmse": 0.0, "r2": 1.0}


def test_undefined_metric_is_none_not_nan():
    assert compute_metrics([5.0], [4.0])["r2"] is None  # R^2 undefined for one sample
    # constant target: sklearn defines R^2 as 1.0 for a perfect fit and 0.0 otherwise; never NaN
    assert compute_metrics([3, 3, 3], [3, 3, 3])["r2"] == 1.0
    assert compute_metrics([3, 3, 3], [3, 3, 4])["r2"] == 0.0
    import json
    json.dumps(compute_metrics([5.0], [4.0]))  # must be serialisable


# ---------------------------------------------------------------- chronological split
def test_split_is_chronological_with_no_overlap(frame):
    train, val, test = chronological_split(frame)
    assert len(train) + len(val) + len(test) == len(frame)
    assert train["date"].max() < val["date"].min() <= val["date"].max() < test["date"].min()
    assert 0.5 < len(train) / len(frame) < 0.7 and len(test) > 0 and len(val) > 0


def test_split_needs_enough_days(frame):
    with pytest.raises(DatasetError):
        chronological_split(frame.assign(date=frame["date"].iloc[0]))


# ---------------------------------------------------------------- comparison results
def test_three_required_algorithms_are_trained_and_scored(result):
    assert [m.name for m in result.models] == ["Linear Regression", "Random Forest", "Gradient Boosting"]
    for m in result.models:
        for split in (m.validation, m.test):
            assert set(split) == {"mae", "rmse", "r2"} and all(v is not None for v in split.values())
            assert split["rmse"] >= split["mae"] >= 0
    assert result.baseline["test"]["mae"] is not None
    assert sum(m.selected for m in result.models) == 1 and result.selected_name


def test_reported_test_metrics_are_reproducible_from_the_saved_model(frame, result):
    _, _, test = chronological_split(frame)
    for m in result.models:
        again = compute_metrics(test[TARGET], m.pipeline.predict(test[FEATURE_COLUMNS]))
        assert again == m.test


def test_models_beat_predicting_the_mean_on_heldout_data(result):
    for m in result.models:
        assert m.test["r2"] > 0.5 and m.eligible  # sanity on SYNTHETIC data only; not a real-world claim


def test_same_seed_gives_identical_metrics(frame, result):
    again = train_and_compare(frame, seed=11)
    assert [(m.validation, m.test) for m in again.models] == [(m.validation, m.test) for m in result.models]


def test_preprocessing_is_fitted_on_training_rows_only(frame, result):
    train, _, _ = chronological_split(frame)
    scaler = result.models[0].pipeline.named_steps["prep"].named_transformers_["num"]
    train_means = FeatureBuilder().transform(train[FEATURE_COLUMNS])[NUMERIC_ALL].mean().to_numpy()
    all_means = FeatureBuilder().transform(frame[FEATURE_COLUMNS])[NUMERIC_ALL].mean().to_numpy()
    np.testing.assert_allclose(scaler.mean_, train_means)
    assert not np.allclose(scaler.mean_, all_means)


# ---------------------------------------------------------------- selection rule
def _tm(name, val_mae, val_rmse, eligible=True):
    return TrainedModel(name, None, {"mae": val_mae, "rmse": val_rmse, "r2": 0.9}, {"mae": 1, "rmse": 1, "r2": 0.9}, eligible)


def test_select_best_rules():
    assert select_best([_tm("A", 5.0, 9), _tm("B", 4.0, 12), _tm("C", 6.0, 8)]).name == "B"
    assert select_best([_tm("A", 4.0, 12), _tm("B", 4.0, 9)]).name == "B"  # tie on MAE -> lower RMSE
    assert select_best([_tm("A", 1.0, 1, eligible=False), _tm("B", 4.0, 9)]).name == "B"  # ineligible never chosen
    assert select_best([_tm("A", 1.0, 1, eligible=False)]) is None
    assert select_best([]) is None


def test_model_worse_than_mean_is_ineligible():
    assert training._is_eligible({"mae": 3, "rmse": 4, "r2": 0.2}) is True
    assert training._is_eligible({"mae": 3, "rmse": 4, "r2": -0.1}) is False
    assert training._is_eligible({"mae": 3, "rmse": 4, "r2": None}) is False


# ---------------------------------------------------------------- persistence and inference
def test_save_load_roundtrip_gives_identical_predictions(tmp_path, frame, result):
    best = next(m for m in result.models if m.selected)
    path = tmp_path / "m.joblib"
    save_model(best.pipeline, path)
    loaded = load_model(path)["pipeline"]
    sample = frame.head(50)[FEATURE_COLUMNS]
    np.testing.assert_allclose(loaded.predict(sample), best.pipeline.predict(sample))


def test_load_rejects_foreign_or_mismatched_files(tmp_path):
    bad = tmp_path / "bad.joblib"
    joblib.dump({"pipeline": object(), "feature_columns": ["something_else"]}, bad)
    with pytest.raises(ValueError):
        load_model(bad)
    joblib.dump([1, 2, 3], bad)
    with pytest.raises(ValueError):
        load_model(bad)


FEATS = dict(service_type="GEN", people_ahead=4, queue_length=6, active_counters=2, busy_counters=2,
             average_service_duration=10.0, staff_count=2, hour=10, day_of_week=1, peak_hour=1)


def test_predict_minutes_output_is_valid(result):
    for m in result.models:
        value = predict_minutes(m.pipeline, FEATS)
        assert isinstance(value, float) and np.isfinite(value) and value >= 0
    assert predict_minutes(result.models[0].pipeline, {**FEATS, "people_ahead": 0, "queue_length": 1, "busy_counters": 0}) >= 0


def test_unknown_service_type_does_not_crash(result):
    for m in result.models:
        assert np.isfinite(predict_minutes(m.pipeline, {**FEATS, "service_type": "NEW"}))


def test_missing_feature_is_an_error(result):
    broken = {k: v for k, v in FEATS.items() if k != "people_ahead"}
    with pytest.raises(KeyError):
        predict_minutes(result.models[0].pipeline, broken)


def test_more_people_ahead_gives_larger_prediction_for_trained_model(result):
    gb = next(m for m in result.models if m.name == "Gradient Boosting")
    few = predict_minutes(gb.pipeline, {**FEATS, "people_ahead": 1, "queue_length": 2})
    many = predict_minutes(gb.pipeline, {**FEATS, "people_ahead": 15, "queue_length": 16})
    assert many > few
