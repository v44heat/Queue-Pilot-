"""Dataset validation and cleaning."""
import numpy as np
import pandas as pd

from .features import DATASET_COLUMNS, TARGET

MIN_ROWS = 200
MIN_DAYS = 5


class DatasetError(ValueError):
    """The dataset cannot be used for training."""


def clean_dataset(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Drop unusable rows. Returns (clean_df, report) where report counts what was removed."""
    # service_duration is known only after service and is never a model input, so it is optional.
    missing = [c for c in DATASET_COLUMNS if c not in df.columns and c != "service_duration"]
    if missing:
        raise DatasetError(f"Dataset is missing required columns: {', '.join(missing)}.")
    df = df.copy()
    if "service_duration" not in df.columns:
        df["service_duration"] = np.nan
    df = df[DATASET_COLUMNS]
    report = {"rows_in": int(len(df))}

    num_cols = [c for c in DATASET_COLUMNS if c not in ("date", "service_type", "service_duration")]
    for c in num_cols + ["service_duration"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["service_type"] = df["service_type"].astype("string").str.strip()

    required = num_cols + ["date", "service_type"]  # service_duration may legitimately be missing
    bad = df[required].isna().any(axis=1) | df["service_type"].eq("") | ~np.isfinite(df[num_cols]).all(axis=1)
    report["dropped_missing_or_invalid"] = int(bad.sum())
    df = df[~bad]

    impossible = (
        (df[["people_ahead", "queue_length", "active_counters", "busy_counters", "staff_count", TARGET]] < 0).any(axis=1)
        | (df["average_service_duration"] <= 0)
        | (df["busy_counters"] > df["active_counters"])
        | (df["active_counters"] < 1)
        | (df["people_ahead"] >= df["queue_length"])
        | ~df["hour"].between(0, 23) | ~df["day_of_week"].between(0, 6)
    )
    report["dropped_impossible"] = int(impossible.sum())
    df = df[~impossible]

    for c in ("people_ahead", "queue_length", "active_counters", "busy_counters", "staff_count", "hour", "day_of_week", "peak_hour"):
        df[c] = df[c].astype(int)
    df["service_type"] = df["service_type"].astype(str)
    report["rows_out"] = int(len(df))
    return df.reset_index(drop=True), report


def validate_dataset(df: pd.DataFrame) -> None:
    """Raise DatasetError if a (cleaned) dataset is unsuitable for a chronological train/validation/test split."""
    if len(df) < MIN_ROWS:
        raise DatasetError(f"At least {MIN_ROWS} valid records are required; found {len(df)}.")
    if df["date"].nunique() < MIN_DAYS:
        raise DatasetError(f"Records must span at least {MIN_DAYS} different days for a chronological split.")
    if df[TARGET].nunique() < 2:
        raise DatasetError("The target (waiting_time) is constant; there is nothing to learn.")
