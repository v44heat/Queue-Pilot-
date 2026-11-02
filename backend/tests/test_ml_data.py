import numpy as np
import pandas as pd
import pytest

from app.ml.dataset import MIN_ROWS, DatasetError, clean_dataset, validate_dataset
from app.ml.features import (
    DATASET_COLUMNS, ENGINEERED, FEATURE_COLUMNS, POST_SERVICE_COLUMNS, TARGET, FeatureBuilder,
    fallback_minutes, validate_feature_values,
)
from app.ml.synthetic import generate_dataset


@pytest.fixture(scope="module")
def big():
    return generate_dataset(20000, seed=1)


# ---------------------------------------------------------------- reproducibility & shape
def test_generation_is_reproducible_and_seed_sensitive():
    a, b, c = generate_dataset(1000, 7), generate_dataset(1000, 7), generate_dataset(1000, 8)
    pd.testing.assert_frame_equal(a, b)
    assert not a.equals(c)


def test_schema_and_value_ranges():
    df = generate_dataset(3000, 3)
    assert list(df.columns) == DATASET_COLUMNS and len(df) == 3000
    assert not df.isna().any().any()
    assert df["date"].is_monotonic_increasing
    assert df["hour"].between(8, 16).all() and df["day_of_week"].between(0, 6).all()
    assert (df["busy_counters"] <= df["active_counters"]).all() and (df["active_counters"] >= 1).all()
    assert (df["people_ahead"] < df["queue_length"]).all() and (df["waiting_time"] >= 0).all()
    assert df["date"].nunique() >= 30 and len(df) >= 1000
    with pytest.raises(ValueError):
        generate_dataset(0)


# ---------------------------------------------------------------- the assumed relationships actually hold
def test_more_people_ahead_means_longer_waits(big):
    assert big["people_ahead"].corr(big[TARGET]) > 0.5
    means = big.groupby(pd.cut(big["people_ahead"], [-1, 2, 6, 12, 30]), observed=True)[TARGET].mean()
    assert means.is_monotonic_increasing


def test_more_free_counters_means_shorter_waits(big):
    busy_line = big[big["people_ahead"].between(6, 12)].copy()
    busy_line["free"] = busy_line["active_counters"] - busy_line["busy_counters"]
    assert busy_line[busy_line["free"] == 0][TARGET].mean() > busy_line[busy_line["free"] >= 2][TARGET].mean()
    heavy = big[big["people_ahead"] >= 8]
    assert heavy[heavy["active_counters"] == 1][TARGET].mean() > heavy[heavy["active_counters"] >= 4][TARGET].mean()


def test_longer_services_mean_longer_waits(big):
    same_load = big[big["people_ahead"].between(5, 10) & (big["active_counters"] == 2)]
    by_service = same_load.groupby("service_type")[TARGET].mean()
    assert by_service["TEC"] > by_service["GEN"] > by_service["DOC"]


def test_peak_hours_have_longer_queues_and_waits(big):
    assert big[big["peak_hour"] == 1]["queue_length"].mean() > big[big["peak_hour"] == 0]["queue_length"].mean()
    assert big[big["peak_hour"] == 1][TARGET].mean() > big[big["peak_hour"] == 0][TARGET].mean()


def test_noise_present_identical_conditions_do_not_give_identical_waits(big):
    g = big.groupby(["service_type", "people_ahead", "active_counters", "busy_counters"])[TARGET]
    stds = g.std()[g.count() >= 8]
    assert len(stds) > 20 and stds.mean() > 0.5


# ---------------------------------------------------------------- leakage prevention
def test_post_service_columns_are_never_model_inputs():
    for col in (*POST_SERVICE_COLUMNS, "date"):
        assert col not in FEATURE_COLUMNS
    assert TARGET in POST_SERVICE_COLUMNS


def test_feature_builder_ignores_target_and_post_service_columns():
    df = generate_dataset(300, 5)
    out = FeatureBuilder().transform(df)
    assert set(out.columns) == set(FEATURE_COLUMNS) | set(ENGINEERED)
    tampered = df.copy()
    tampered[TARGET] = 999.0
    tampered["service_duration"] = 999.0
    tampered["date"] = "1999-01-01"
    pd.testing.assert_frame_equal(out, FeatureBuilder().transform(tampered))


# ---------------------------------------------------------------- cleaning & validation
def test_clean_drops_bad_rows_and_reports_counts():
    df = generate_dataset(500, 2)
    df.loc[0, "people_ahead"] = np.nan
    df.loc[1, "service_type"] = ""
    df.loc[2, "busy_counters"] = df.loc[2, "active_counters"] + 1
    df.loc[3, TARGET] = -5
    df.loc[4, "average_service_duration"] = 0
    df.loc[5, "hour"] = 30
    clean, report = clean_dataset(df)
    assert report["rows_in"] == 500 and report["rows_out"] == 494
    assert report["dropped_missing_or_invalid"] == 2 and report["dropped_impossible"] == 4
    assert clean["people_ahead"].dtype.kind == "i" and str(clean["date"].dtype).startswith("datetime64")


def test_service_duration_is_optional_but_other_columns_are_required():
    df = generate_dataset(300, 2)
    clean, _ = clean_dataset(df.drop(columns=["service_duration"]))
    assert len(clean) == 300
    with pytest.raises(DatasetError, match="missing required columns"):
        clean_dataset(df.drop(columns=["people_ahead"]))


def test_validate_dataset_rules():
    ok, _ = clean_dataset(generate_dataset(1000, 2))
    validate_dataset(ok)
    with pytest.raises(DatasetError, match=str(MIN_ROWS)):
        validate_dataset(ok.head(MIN_ROWS - 1))
    with pytest.raises(DatasetError, match="different days"):
        validate_dataset(ok.assign(date=ok["date"].iloc[0]))
    with pytest.raises(DatasetError, match="constant"):
        validate_dataset(ok.assign(**{TARGET: 5.0}))


# ---------------------------------------------------------------- feature validation & fallback formula
GOOD = dict(service_type="GEN", people_ahead=3, queue_length=5, active_counters=2, busy_counters=1,
            average_service_duration=10.0, staff_count=2, hour=10, day_of_week=2, peak_hour=1)


def test_validate_feature_values_accepts_good_and_rejects_bad():
    validate_feature_values(GOOD)
    for bad in (dict(people_ahead=-1), dict(people_ahead=5), dict(busy_counters=3), dict(hour=24), dict(day_of_week=7),
                dict(peak_hour=2), dict(average_service_duration=0), dict(service_type=""), dict(active_counters=True),
                dict(queue_length=2.5), dict(people_ahead="3")):
        with pytest.raises(ValueError):
            validate_feature_values({**GOOD, **bad})


def test_fallback_formula():
    assert float(fallback_minutes(6, 10, 2)) == 30.0
    assert float(fallback_minutes(0, 10, 3)) == 0.0
    assert list(fallback_minutes(np.array([2, 4]), np.array([5, 5]), np.array([1, 2]))) == [10.0, 10.0]
    assert float(fallback_minutes(5, 10, 0)) == 50.0  # never divides by zero
