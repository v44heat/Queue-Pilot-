"""System settings: a fixed catalogue of validated, administrator-editable values.

Only keys in CATALOG can be stored. A missing row means "use the default", so resetting a
setting simply deletes its row. Updates are all-or-nothing.
"""
from ..extensions import db
from ..models.setting import SystemSetting

CATALOG: dict[str, dict] = {
    "congestion.moderate_min": {
        "type": "int", "default": 5, "min": 1, "max": 1000, "group": "Congestion",
        "label": "MODERATE starts at (waiting customers)",
        "description": "A service with fewer waiting customers than this is LOW. This value is the first MODERATE count (inclusive).",
    },
    "congestion.high_min": {
        "type": "int", "default": 11, "min": 2, "max": 1000, "group": "Congestion",
        "label": "HIGH starts at (waiting customers)",
        "description": "First waiting count (inclusive) that is HIGH. Must be above the MODERATE value.",
    },
    "congestion.critical_min": {
        "type": "int", "default": 21, "min": 3, "max": 1000, "group": "Congestion",
        "label": "CRITICAL starts at (waiting customers)",
        "description": "First waiting count (inclusive) that is CRITICAL. Must be above the HIGH value.",
    },
    "notifications.approaching_ahead": {
        "type": "int", "default": 2, "min": 0, "max": 10, "group": "Customer notifications",
        "label": "'Turn approaching' when this many people or fewer are ahead",
        "description": "0 means only the customer who is next is told.",
    },
    "notifications.wait_change_minutes": {
        "type": "float", "default": 10.0, "min": 1.0, "max": 120.0, "group": "Customer notifications",
        "label": "Waiting-time change that triggers an update (minutes)",
        "description": "An update is sent only if the estimate changed by at least this many minutes AND by the percentage below.",
    },
    "notifications.wait_change_ratio": {
        "type": "float", "default": 0.25, "min": 0.05, "max": 5.0, "group": "Customer notifications",
        "label": "Waiting-time change that triggers an update (fraction)",
        "description": "0.25 means 25% of the previously announced estimate (at least 1 minute is used as the base).",
    },
}
CONGESTION_ORDER = ("congestion.moderate_min", "congestion.high_min", "congestion.critical_min")


class SettingsError(Exception):
    def __init__(self, details: dict):
        super().__init__("Invalid settings.")
        self.details = details


def _parse(key: str, raw: str):
    spec = CATALOG[key]
    try:
        return int(raw) if spec["type"] == "int" else float(raw)
    except (TypeError, ValueError):
        return spec["default"]


def get(key: str):
    """Current effective value (stored value if valid, otherwise the default)."""
    spec = CATALOG[key]
    row = SystemSetting.query.filter_by(setting_name=key).first()
    return spec["default"] if row is None else _parse(key, row.setting_value)


def _stored() -> dict[str, SystemSetting]:
    return {r.setting_name: r for r in SystemSetting.query.all()}


def get_all() -> list[dict]:
    stored = _stored()
    out = []
    for key, spec in CATALOG.items():
        row = stored.get(key)
        value = spec["default"] if row is None else _parse(key, row.setting_value)
        out.append({
            "key": key, "value": value, "default": spec["default"], "is_default": row is None,
            "type": spec["type"], "min": spec["min"], "max": spec["max"], "group": spec["group"],
            "label": spec["label"], "description": spec["description"],
            "updated_at": row.updated_at.isoformat() if row and row.updated_at else None,
        })
    return out


def _coerce(key: str, raw):
    """Validate one value. Returns (value, error)."""
    spec = CATALOG[key]
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None, "Must be a number."
    if spec["type"] == "int":
        if isinstance(raw, float) and not raw.is_integer():
            return None, "Must be a whole number."
        value = int(raw)
    else:
        value = float(raw)
    if not (spec["min"] <= value <= spec["max"]):
        return None, f"Must be between {spec['min']} and {spec['max']}."
    return value, None


def update(changes: dict, user=None) -> list[dict]:
    """Apply changes atomically. A value of null resets that setting to its default."""
    if not isinstance(changes, dict) or not changes:
        raise SettingsError({"_": "Provide at least one setting."})
    errors: dict[str, str] = {}
    parsed: dict = {}
    for key, raw in changes.items():
        if key not in CATALOG:
            errors[key] = "Unknown setting."
        elif raw is None:
            parsed[key] = None
        else:
            value, err = _coerce(key, raw)
            if err:
                errors[key] = err
            else:
                parsed[key] = value
    if not errors:  # cross-field rule on the values that would be in effect afterwards
        eff = {k: (CATALOG[k]["default"] if parsed.get(k, get(k)) is None else parsed.get(k, get(k))) for k in CONGESTION_ORDER}
        if not eff[CONGESTION_ORDER[0]] < eff[CONGESTION_ORDER[1]]:
            errors[CONGESTION_ORDER[1]] = "Must be greater than the MODERATE value."
        if not eff[CONGESTION_ORDER[1]] < eff[CONGESTION_ORDER[2]]:
            errors[CONGESTION_ORDER[2]] = "Must be greater than the HIGH value."
    if errors:
        raise SettingsError(errors)

    stored = _stored()
    for key, value in parsed.items():
        row = stored.get(key)
        if value is None:
            if row is not None:
                db.session.delete(row)
        elif row is None:
            db.session.add(SystemSetting(setting_name=key, setting_value=repr(value), updated_by=getattr(user, "id", None)))
        else:
            row.setting_value, row.updated_by = repr(value), getattr(user, "id", None)
    db.session.commit()
    return get_all()
