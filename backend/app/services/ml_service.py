"""Training orchestration, model registry, activation and live performance."""
import uuid
from pathlib import Path

import pandas as pd
import sklearn
from flask import current_app
from sqlalchemy import func

from ..extensions import db
from ..ml import training
from ..ml.dataset import DatasetError, clean_dataset, validate_dataset
from ..ml.synthetic import generate_dataset
from ..models.ml import ModelVersion, PredictionLog
from .queue_service import QueueError, _local_tz

SOURCES = ("synthetic", "historical", "mixed")
_CACHE: dict = {}  # (model_version_id, file mtime) -> loaded pipeline


# ---- artifact files --------------------------------------------------------------------------
def artifact_dir() -> Path:
    return Path(current_app.config["ML_ARTIFACT_DIR"]).resolve()


def resolve_artifact(relative: str) -> Path:
    """Resolve a stored model path and refuse anything outside the artifact folder."""
    base = artifact_dir()
    path = (base / relative).resolve()
    if base != path and base not in path.parents:
        raise ValueError("Model path is outside the artifact directory.")
    return path


def clear_model_cache() -> None:
    _CACHE.clear()


def load_pipeline(mv: ModelVersion):
    path = resolve_artifact(mv.model_path)
    key = (mv.id, path.stat().st_mtime_ns)
    if key not in _CACHE:
        _CACHE.clear()  # keep at most one model in memory
        _CACHE[key] = training.load_model(path)["pipeline"]
    return _CACHE[key]


def active_model_version() -> ModelVersion | None:
    return ModelVersion.query.filter_by(is_active=True).first()


# ---- datasets --------------------------------------------------------------------------------
def historical_frame() -> pd.DataFrame:
    """Training rows from the application's own data: the feature snapshot saved when each
    prediction was made, paired with the waiting time actually measured later."""
    rows = []
    tz = _local_tz()
    logs = PredictionLog.query.filter(PredictionLog.actual_value.isnot(None)).all()
    for log in logs:
        f = log.features or {}
        created = log.created_at if log.created_at.tzinfo else log.created_at.replace(tzinfo=__import__("datetime").timezone.utc)
        rows.append({
            "date": created.astimezone(tz).date().isoformat(), "day_of_week": f.get("day_of_week"),
            "hour": f.get("hour"), "service_type": f.get("service_type"), "queue_length": f.get("queue_length"),
            "people_ahead": f.get("people_ahead"), "active_counters": f.get("active_counters"),
            "busy_counters": f.get("busy_counters"), "average_service_duration": f.get("average_service_duration"),
            "staff_count": f.get("staff_count"), "peak_hour": f.get("peak_hour"),
            "waiting_time": log.actual_value, "service_duration": log.ticket.service_duration if log.ticket else None,
        })
    return pd.DataFrame(rows)


def build_training_frame(source: str, rows: int, seed: int) -> pd.DataFrame:
    if source not in SOURCES:
        raise QueueError("validation_error", f"source must be one of {', '.join(SOURCES)}.", 400)
    frames = []
    if source in ("synthetic", "mixed"):
        frames.append(generate_dataset(rows, seed))
    if source in ("historical", "mixed"):
        hist = historical_frame()
        if source == "historical" and len(hist) == 0:
            raise QueueError("insufficient_data", "No completed tickets with recorded predictions exist yet.", 409)
        if len(hist):
            frames.append(hist)
    return pd.concat(frames, ignore_index=True)


# ---- training --------------------------------------------------------------------------------
def _slug(name: str) -> str:
    return name.lower().replace(" ", "_")


def train_run(source: str = "synthetic", rows: int = 6000, seed: int = 42, activate_best: bool = False) -> list[ModelVersion]:
    """Train and compare the three regressors, persist them, and register each as a ModelVersion."""
    raw = build_training_frame(source, rows, seed)
    try:
        clean, report = clean_dataset(raw)
        validate_dataset(clean)
        result = training.train_and_compare(clean, seed)
    except DatasetError as e:
        raise QueueError("insufficient_data", str(e), 409)

    run_id = str(uuid.uuid4())
    run_dir = artifact_dir() / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    versions = []
    for m in result.models:
        n = ModelVersion.query.filter_by(model_name=m.name).count() + 1
        relative = f"{run_id}/{_slug(m.name)}.joblib"
        training.save_model(m.pipeline, artifact_dir() / relative)
        mv = ModelVersion(
            model_name=m.name, version=f"{n}.0", run_id=run_id, mae=m.test["mae"], rmse=m.test["rmse"], r2=m.test["r2"],
            model_path=relative, data_source=source, is_active=False,
            details={
                "validation": m.validation, "test": m.test, "eligible": m.eligible, "selected_in_run": m.selected,
                "split": result.split, "cleaning": report, "baseline": result.baseline, "rows": int(len(clean)),
                "seed": seed, "sklearn_version": sklearn.__version__,
                "selection_rule": "lowest validation MAE among eligible models (ties: lower RMSE, then name)",
            },
        )
        db.session.add(mv)
        versions.append(mv)
    db.session.commit()
    current_app.logger.info("ML run %s trained %d models (source=%s, rows=%d, best=%s)",
                            run_id, len(versions), source, len(clean), result.selected_name)
    if activate_best:
        best = next((v for v in versions if v.details["selected_in_run"]), None)
        if best:
            activate(best.id)
    return versions


# ---- activation ------------------------------------------------------------------------------
def activate(model_id: int) -> ModelVersion:
    mv = db.session.get(ModelVersion, model_id)
    if mv is None:
        raise QueueError("model_not_found", "Model not found.", 404)
    if not (mv.details or {}).get("eligible"):
        raise QueueError("model_ineligible", "This model did not beat the mean-prediction test (R² must be above 0) and cannot be activated.", 409)
    try:
        load_pipeline(mv)  # must be loadable before it can serve predictions
    except Exception:  # noqa: BLE001
        current_app.logger.exception("Model %s failed to load during activation", mv.id)
        raise QueueError("model_unloadable", "The model file is missing or unreadable.", 409)
    ModelVersion.query.filter(ModelVersion.is_active.is_(True), ModelVersion.id != mv.id).update({"is_active": False})
    db.session.flush()
    mv.is_active = True
    db.session.commit()
    return mv


# ---- live performance (from real prediction logs) ----------------------------------------------
def live_performance() -> dict:
    """Accuracy of predictions actually made by the running system, once real waits are known."""
    out = {}
    q = (
        db.session.query(PredictionLog.source, PredictionLog.model_version_id)
        .filter(PredictionLog.actual_value.isnot(None)).group_by(PredictionLog.source, PredictionLog.model_version_id).all()
    )
    for source, mv_id in q:
        logs = PredictionLog.query.filter(
            PredictionLog.actual_value.isnot(None), PredictionLog.source == source, PredictionLog.model_version_id == mv_id).all()
        n = len(logs)
        label = "fallback" if mv_id is None else f"model_{mv_id}"
        mv = db.session.get(ModelVersion, mv_id) if mv_id else None
        entry = {"source": source, "model_version_id": mv_id, "n": n,
                 "model": None if mv is None else f"{mv.model_name} {mv.version}"}
        entry.update(training.compute_metrics([l.actual_value for l in logs], [l.prediction for l in logs]) if n >= 2
                     else {"mae": None, "rmse": None, "r2": None})
        out[label] = entry
    pending = db.session.query(func.count(PredictionLog.id)).filter(PredictionLog.actual_value.is_(None)).scalar()
    return {"groups": list(out.values()), "predictions_awaiting_outcome": pending}
