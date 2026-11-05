from flask import Blueprint, current_app, g, jsonify, request

from ..services import settings_service
from ..utils.auth import error, roles_required

settings_bp = Blueprint("settings", __name__)


@settings_bp.get("")
@roles_required("ADMIN")
def list_settings():
    return jsonify(settings=settings_service.get_all())


@settings_bp.patch("")
@roles_required("ADMIN")
def update_settings():
    """Body: {"settings": {"congestion.high_min": 12, "notifications.approaching_ahead": null}}.
    A null value resets that setting to its default. All changes apply together or not at all."""
    body = request.get_json(silent=True)
    changes = body.get("settings") if isinstance(body, dict) else None
    try:
        result = settings_service.update(changes, g.current_user)
    except settings_service.SettingsError as e:
        return error("validation_error", "Please correct the highlighted settings.", 400, e.details)
    current_app.logger.info("Admin id=%s changed settings %s", g.current_user.id, sorted(changes))
    return jsonify(settings=result)
