from unittest.mock import patch

import pytest

from app import create_app


def test_health_ok(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.get_json()["status"] == "ok"


def test_health_db_ok(client):
    res = client.get("/api/health/db")
    assert res.status_code == 200
    body = res.get_json()
    assert body["status"] == "ok" and body["database"] == "connected"


def test_health_db_failure_returns_503_without_details(app, client):
    with patch("app.routes.health.db.session.execute", side_effect=RuntimeError("secret dsn")):
        res = client.get("/api/health/db")
    assert res.status_code == 503
    assert "secret" not in res.get_data(as_text=True)


def test_unknown_route_json_404(client):
    res = client.get("/api/nope")
    assert res.status_code == 404
    assert res.get_json()["error"] == "not_found"


def test_missing_config_raises(monkeypatch):
    from app.config import DevelopmentConfig

    monkeypatch.setattr(DevelopmentConfig, "SECRET_KEY", None)
    with pytest.raises(RuntimeError):
        create_app("development")
