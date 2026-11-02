"""Feature definitions shared by training and prediction (single source of truth).

Leakage rules
-------------
Only values that exist at the moment a customer joins (or when an estimate is refreshed)
are model inputs. `waiting_time` (the target) and `service_duration` (known only after
service ends) are NEVER inputs, and `date` is used only for chronological splitting.
FeatureBuilder keeps only FEATURE_COLUMNS, so a stray column cannot leak into the model.
"""
import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin

# Hours (local time, 0-23) treated as peak. A documented, adjustable assumption.
PEAK_HOURS = frozenset({9, 10, 11, 14, 15})

TARGET = "waiting_time"
POST_SERVICE_COLUMNS = ("waiting_time", "service_duration")  # unknown at prediction time

CATEGORICAL = ["service_type"]
BASE_NUMERIC = [
    "people_ahead", "queue_length", "active_counters", "busy_counters",
    "average_service_duration", "staff_count", "hour", "day_of_week", "peak_hour",
]
FEATURE_COLUMNS = BASE_NUMERIC + CATEGORICAL
# Deterministic functions of the base features (so no extra information is introduced).
ENGINEERED = ["available_counters", "load_ratio", "workload_minutes"]
NUMERIC_ALL = BASE_NUMERIC + ENGINEERED

DATASET_COLUMNS = [
    "date", "day_of_week", "hour", "service_type", "queue_length", "people_ahead", "active_counters",
    "busy_counters", "average_service_duration", "staff_count", "peak_hour", "waiting_time", "service_duration",
]


def is_peak_hour(hour: int) -> int:
    return int(hour in PEAK_HOURS)


def fallback_minutes(people_ahead, average_service_duration, active_counters):
    """Documented rule-of-thumb used when no trained model is usable (also the evaluation baseline):

        wait = (people_ahead / open counters) x average service duration

    Works on scalars and numpy/pandas arrays. Requires at least one open counter."""
    active = np.maximum(np.asarray(active_counters, dtype=float), 1.0)
    return np.asarray(people_ahead, dtype=float) / active * np.asarray(average_service_duration, dtype=float)


class FeatureBuilder(BaseEstimator, TransformerMixin):
    """Select the allowed inputs and add engineered columns. Stateless, so it cannot leak."""

    def fit(self, X, y=None):
        return self

    def transform(self, X):
        df = pd.DataFrame(X)[FEATURE_COLUMNS].copy()
        df["available_counters"] = df["active_counters"] - df["busy_counters"]
        df["load_ratio"] = df["people_ahead"] / df["active_counters"].clip(lower=1)
        df["workload_minutes"] = df["load_ratio"] * df["average_service_duration"]
        return df


def validate_feature_values(f: dict) -> None:
    """Range/consistency checks for a single prediction request. Raises ValueError."""
    for key in ("people_ahead", "queue_length", "active_counters", "busy_counters", "staff_count"):
        v = f[key]
        if isinstance(v, bool) or not isinstance(v, (int, np.integer)) or v < 0 or v > 10_000:
            raise ValueError(f"{key} must be a non-negative integer.")
    if not isinstance(f["average_service_duration"], (int, float)) or not (0 < f["average_service_duration"] <= 600):
        raise ValueError("average_service_duration must be between 0 and 600 minutes.")
    if f["hour"] not in range(24) or f["day_of_week"] not in range(7) or f["peak_hour"] not in (0, 1):
        raise ValueError("hour, day_of_week or peak_hour is out of range.")
    if not isinstance(f["service_type"], str) or not f["service_type"]:
        raise ValueError("service_type is required.")
    if f["busy_counters"] > f["active_counters"]:
        raise ValueError("busy_counters cannot exceed active_counters.")
    if f["people_ahead"] >= f["queue_length"]:
        raise ValueError("people_ahead must be smaller than queue_length (the customer counts in the queue).")
