"""CSV reports (administrators only). Every figure comes from the same queries as the analytics endpoints."""
import calendar
from datetime import date, timedelta

from flask import Blueprint, request

from ..models.ml import ModelVersion
from ..services import analytics_service as an
from ..services.queue_service import QueueError, _local_today
from ..utils.auth import roles_required
from ..utils.csv_export import csv_response

reports_bp = Blueprint("reports", __name__)

BREAKDOWN_COLUMNS = [
    ("date", "Date"), ("service", "Service"), ("prefix", "Prefix"), ("joined", "Tickets joined"), ("completed", "Completed"),
    ("cancelled", "Cancelled"), ("skipped", "Skipped"), ("absent", "Absent"), ("in_progress", "Still in queue or serving"),
    ("avg_waiting", "Average waiting (min)"), ("max_waiting", "Longest waiting (min)"), ("avg_service_duration", "Average service (min)"),
]
SERVICE_COLUMNS = [
    ("service", "Service"), ("prefix", "Prefix"), ("joined", "Tickets joined"), ("completed", "Completed"),
    ("completion_rate", "Completion rate (0-1)"), ("cancelled", "Cancelled"), ("skipped", "Skipped"), ("absent", "Absent"),
    ("in_progress", "Still in queue or serving"), ("avg_waiting", "Average waiting (min)"), ("max_waiting", "Longest waiting (min)"),
    ("avg_service_duration", "Average service (min)"),
]
COUNTER_COLUMNS = [
    ("counter", "Counter"), ("service", "Service"), ("open_minutes", "Open (min)"), ("serving_minutes", "Serving (min)"),
    ("utilization", "Utilization (0-1)"), ("customers_served", "Customers served"), ("avg_service_duration", "Average service (min)"),
]
MODEL_COLUMNS = [
    ("model_name", "Model"), ("version", "Version"), ("data_source", "Training data"), ("training_date", "Trained (UTC)"),
    ("rows", "Usable rows"), ("seed", "Seed"), ("is_active", "Active"), ("eligible", "Eligible"), ("selected_in_run", "Selected in its run"),
    ("val_mae", "Validation MAE (min)"), ("val_rmse", "Validation RMSE (min)"), ("val_r2", "Validation R2"),
    ("mae", "Test MAE (min)"), ("rmse", "Test RMSE (min)"), ("r2", "Test R2"),
    ("base_mae", "Baseline test MAE (min)"), ("base_rmse", "Baseline test RMSE (min)"), ("base_r2", "Baseline test R2"),
]


def _date_arg(name: str, default: date) -> date:
    raw = request.args.get(name)
    if not raw:
        return default
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise QueueError("validation_error", f"{name} must look like 2026-03-02.", 400)


@reports_bp.get("/daily")
@roles_required("ADMIN")
def daily():
    d = _date_arg("date", _local_today())
    return csv_response(f"queuepilot-daily-{d.isoformat()}.csv", BREAKDOWN_COLUMNS, an.daily_service_breakdown(d, d))


@reports_bp.get("/weekly")
@roles_required("ADMIN")
def weekly():
    """The Monday-to-Sunday week that contains `date` (default: this week)."""
    d = _date_arg("date", _local_today())
    monday = d - timedelta(days=d.weekday())
    return csv_response(f"queuepilot-weekly-{monday.isoformat()}.csv", BREAKDOWN_COLUMNS,
                        an.daily_service_breakdown(monday, monday + timedelta(days=6)))


@reports_bp.get("/monthly")
@roles_required("ADMIN")
def monthly():
    raw = request.args.get("month")
    try:
        first = date.fromisoformat(f"{raw}-01") if raw else _local_today().replace(day=1)
    except ValueError:
        raise QueueError("validation_error", "month must look like 2026-03.", 400)
    last = first.replace(day=calendar.monthrange(first.year, first.month)[1])
    return csv_response(f"queuepilot-monthly-{first:%Y-%m}.csv", BREAKDOWN_COLUMNS, an.daily_service_breakdown(first, last))


@reports_bp.get("/services")
@roles_required("ADMIN")
def services():
    start, end = an.parse_range(request.args, default_days=30)
    rows = an.service_performance(start, end)["services"]
    return csv_response(f"queuepilot-services-{start.isoformat()}_{end.isoformat()}.csv", SERVICE_COLUMNS, rows)


@reports_bp.get("/counters")
@roles_required("ADMIN")
def counters():
    start, end = an.parse_range(request.args, default_days=30)
    rows = an.counter_utilization(start, end)["counters"]
    return csv_response(f"queuepilot-counters-{start.isoformat()}_{end.isoformat()}.csv", COUNTER_COLUMNS, rows)


@reports_bp.get("/models")
@roles_required("ADMIN")
def models():
    rows = []
    for m in ModelVersion.query.order_by(ModelVersion.training_date.desc(), ModelVersion.id.desc()).all():
        d = m.details or {}
        val, base = d.get("validation") or {}, (d.get("baseline") or {}).get("test") or {}
        rows.append({
            "model_name": m.model_name, "version": m.version, "data_source": m.data_source,
            "training_date": m.training_date.isoformat() if m.training_date else None,
            "rows": d.get("rows"), "seed": d.get("seed"), "is_active": m.is_active, "eligible": d.get("eligible"),
            "selected_in_run": d.get("selected_in_run"), "val_mae": val.get("mae"), "val_rmse": val.get("rmse"), "val_r2": val.get("r2"),
            "mae": m.mae, "rmse": m.rmse, "r2": m.r2, "base_mae": base.get("mae"), "base_rmse": base.get("rmse"), "base_r2": base.get("r2"),
        })
    return csv_response("queuepilot-ml-models.csv", MODEL_COLUMNS, rows)
