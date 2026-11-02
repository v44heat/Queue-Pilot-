"""Model training, chronological evaluation and model selection (pure ML; no Flask/DB).

Evaluation strategy (documented in docs/ml-methodology.md)
----------------------------------------------------------
1. Split CHRONOLOGICALLY by calendar day: first 60% of days = train, next 20% = validation,
   last 20% = test. No future day ever appears in an earlier set.
2. Every preprocessing step (scaling, one-hot encoding) lives inside the sklearn Pipeline and is
   fitted on the training rows only.
3. Models are compared and the best is SELECTED on validation MAE (ties: lower RMSE, then name).
4. The test set is touched only to report the final, unbiased MAE / RMSE / R^2.
5. A model is ELIGIBLE for activation only if its metrics are finite and test R^2 > 0
   (it must beat always predicting the mean).
6. A rule-based baseline (the fallback formula) is scored on the same splits for context.
"""
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from .dataset import DatasetError
from .features import CATEGORICAL, FEATURE_COLUMNS, NUMERIC_ALL, TARGET, FeatureBuilder, fallback_minutes

SPLIT_FRACTIONS = (0.6, 0.2, 0.2)
RF_PARAMS = {"n_estimators": 150, "min_samples_leaf": 3, "n_jobs": 1}
GB_PARAMS = {"n_estimators": 200, "learning_rate": 0.05, "max_depth": 3}


@dataclass
class TrainedModel:
    name: str
    pipeline: Pipeline
    validation: dict
    test: dict
    eligible: bool
    selected: bool = False


@dataclass
class TrainingResult:
    models: list
    baseline: dict
    split: dict
    selected_name: str | None = None
    extras: dict = field(default_factory=dict)


# ---- metrics ---------------------------------------------------------------------------------
def compute_metrics(y_true, y_pred) -> dict:
    """MAE, RMSE (same unit as the target: minutes) and R^2. Non-finite values become None."""
    y_true, y_pred = np.asarray(y_true, dtype=float), np.asarray(y_pred, dtype=float)
    out = {
        "mae": float(mean_absolute_error(y_true, y_pred)),
        "rmse": float(math.sqrt(mean_squared_error(y_true, y_pred))),
        "r2": float(r2_score(y_true, y_pred)) if len(y_true) > 1 else float("nan"),
    }
    return {k: (round(v, 4) if math.isfinite(v) else None) for k, v in out.items()}


def _is_eligible(test_metrics: dict) -> bool:
    return all(v is not None for v in test_metrics.values()) and test_metrics["r2"] > 0


def select_best(candidates: list) -> TrainedModel | None:
    """Best ELIGIBLE model by validation MAE, then validation RMSE, then name."""
    pool = [c for c in candidates if c.eligible and c.validation["mae"] is not None]
    if not pool:
        return None
    return min(pool, key=lambda c: (c.validation["mae"], c.validation["rmse"] if c.validation["rmse"] is not None else math.inf, c.name))


# ---- splitting -------------------------------------------------------------------------------
def chronological_split(df: pd.DataFrame, fractions=SPLIT_FRACTIONS):
    """Split by whole days: earlier days train, later days validate/test. Returns (train, val, test)."""
    days = np.sort(df["date"].dt.normalize().unique())
    if len(days) < 3:
        raise DatasetError("At least 3 different days are needed for a train/validation/test split.")
    i1 = max(int(len(days) * fractions[0]), 1)
    i2 = max(int(len(days) * (fractions[0] + fractions[1])), i1 + 1)
    i2 = min(i2, len(days) - 1)
    d = df["date"].dt.normalize()
    train, val, test = df[d < days[i1]], df[(d >= days[i1]) & (d < days[i2])], df[d >= days[i2]]
    if min(len(train), len(val), len(test)) == 0:
        raise DatasetError("The split produced an empty set; provide more data.")
    return train, val, test


# ---- pipelines -------------------------------------------------------------------------------
def make_pipeline(model) -> Pipeline:
    prep = ColumnTransformer([
        ("num", StandardScaler(), NUMERIC_ALL),
        ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL),
    ])
    return Pipeline([("features", FeatureBuilder()), ("prep", prep), ("model", model)])


def candidate_models(seed: int) -> dict:
    return {
        "Linear Regression": LinearRegression(),
        "Random Forest": RandomForestRegressor(random_state=seed, **RF_PARAMS),
        "Gradient Boosting": GradientBoostingRegressor(random_state=seed, **GB_PARAMS),
    }


def _baseline_scores(frame: pd.DataFrame) -> dict:
    pred = fallback_minutes(frame["people_ahead"], frame["average_service_duration"], frame["active_counters"])
    return compute_metrics(frame[TARGET], pred)


def train_and_compare(df: pd.DataFrame, seed: int = 42) -> TrainingResult:
    """Train the three required regressors on the training days and evaluate them honestly."""
    train, val, test = chronological_split(df)
    models = []
    for name, estimator in candidate_models(seed).items():
        pipe = make_pipeline(estimator)
        pipe.fit(train[FEATURE_COLUMNS], train[TARGET])  # preprocessing fitted on training rows only
        v = compute_metrics(val[TARGET], pipe.predict(val[FEATURE_COLUMNS]))
        t = compute_metrics(test[TARGET], pipe.predict(test[FEATURE_COLUMNS]))
        models.append(TrainedModel(name, pipe, v, t, _is_eligible(t)))
    best = select_best(models)
    if best:
        best.selected = True
    span = lambda f: [f["date"].min().date().isoformat(), f["date"].max().date().isoformat()]  # noqa: E731
    return TrainingResult(
        models=models,
        baseline={"name": "Rule-based fallback (baseline)", "validation": _baseline_scores(val), "test": _baseline_scores(test)},
        split={
            "strategy": "chronological by day, 60/20/20",
            "n_train": len(train), "n_validation": len(val), "n_test": len(test),
            "train_dates": span(train), "validation_dates": span(val), "test_dates": span(test),
        },
        selected_name=best.name if best else None,
    )


# ---- persistence & inference -------------------------------------------------------------------
def save_model(pipeline: Pipeline, path) -> None:
    joblib.dump({
        "pipeline": pipeline,
        "feature_columns": FEATURE_COLUMNS,
        "sklearn_version": sklearn.__version__,
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }, path, compress=3)


def load_model(path) -> dict:
    """Load a bundle saved by save_model. Only call with paths inside the application's artifact folder."""
    bundle = joblib.load(path)
    if not isinstance(bundle, dict) or "pipeline" not in bundle or bundle.get("feature_columns") != FEATURE_COLUMNS:
        raise ValueError("Model file does not match the current feature definition.")
    return bundle


def predict_minutes(pipeline: Pipeline, features: dict) -> float:
    """Predict waiting minutes for ONE feature dict; never negative."""
    row = pd.DataFrame([{c: features[c] for c in FEATURE_COLUMNS}])
    value = float(pipeline.predict(row)[0])
    if not math.isfinite(value):
        raise ValueError("Model produced a non-finite prediction.")
    return max(value, 0.0)
