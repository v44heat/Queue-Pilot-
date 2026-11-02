import csv

import pytest

from app.models.ml import ModelVersion, PredictionLog
from app.services import ml_service

pytestmark = pytest.mark.usefixtures("fast_models")


@pytest.fixture()
def adm(client, make_user, login):
    make_user("ADMIN", "admin@example.com")
    make_user("STAFF", "staff@example.com")
    make_user("CUSTOMER", "cust@example.com")
    return type("A", (), dict(h=login("admin@example.com"), hs=login("staff@example.com"), hc=login("cust@example.com")))


def train(client, h, **body):
    return client.post("/api/ml/train", json={"rows": 600, **body}, headers=h)


def test_only_admins_may_manage_models(client, adm):
    for h in (adm.hs, adm.hc):
        assert client.get("/api/ml/models", headers=h).status_code == 403
        assert train(client, h).status_code == 403
        assert client.post("/api/ml/models/1/activate", headers=h).status_code == 403
        assert client.get("/api/ml/performance", headers=h).status_code == 403
        assert client.get("/api/ml/prediction-logs", headers=h).status_code == 403
    assert client.get("/api/ml/models").status_code == 401


def test_training_compares_three_models_with_measured_metrics(client, adm):
    res = train(client, adm.h)
    assert res.status_code == 201
    models = res.get_json()["models"]
    assert [m["model_name"] for m in models] == ["Linear Regression", "Random Forest", "Gradient Boosting"]
    assert sum(m["selected_in_run"] for m in models) == 1
    for m in models:
        assert m["version"] == "1.0" and m["data_source"] == "synthetic" and m["is_active"] is False
        assert all(isinstance(m[k], float) for k in ("mae", "rmse", "r2"))
        assert set(m["validation"]) == {"mae", "rmse", "r2"} and m["baseline"]["test"]["mae"] > 0
        assert m["split"]["strategy"].startswith("chronological")
    # metrics in the registry are the held-out test metrics, not invented numbers
    row = ModelVersion.query.filter_by(model_name="Random Forest").one()
    assert row.mae == row.details["test"]["mae"] and row.mae != row.details["validation"]["mae"]
    assert train(client, adm.h).get_json()["models"][0]["version"] == "2.0"


def test_training_validates_input_and_reports_data_problems(client, adm):
    for bad in (dict(rows=10), dict(rows=10**7), dict(rows=True), dict(rows="600"), dict(seed=-1), dict(seed=1.5)):
        assert train(client, adm.h, **bad).status_code == 400, bad
    assert train(client, adm.h, source="bogus").status_code == 400
    res = train(client, adm.h, source="historical")
    assert res.status_code == 409 and res.get_json()["error"] == "insufficient_data"


def test_list_and_activate_models(client, adm):
    ids = [m["id"] for m in train(client, adm.h).get_json()["models"]]
    assert len(client.get("/api/ml/models", headers=adm.h).get_json()["models"]) == 3
    res = client.post(f"/api/ml/models/{ids[1]}/activate", headers=adm.h)
    assert res.status_code == 200 and res.get_json()["model"]["is_active"] is True
    client.post(f"/api/ml/models/{ids[2]}/activate", headers=adm.h)
    listing = {m["id"]: m["is_active"] for m in client.get("/api/ml/models", headers=adm.h).get_json()["models"]}
    assert listing == {ids[0]: False, ids[1]: False, ids[2]: True}
    assert client.post("/api/ml/models/9999/activate", headers=adm.h).status_code == 404


def test_cannot_activate_an_ineligible_model(client, adm):
    mid = train(client, adm.h).get_json()["models"][0]["id"]
    row = ModelVersion.query.get(mid)
    row.details = {**row.details, "eligible": False}
    from app.extensions import db
    db.session.commit()
    res = client.post(f"/api/ml/models/{mid}/activate", headers=adm.h)
    assert res.status_code == 409 and res.get_json()["error"] == "model_ineligible"


def test_activate_best_flag_activates_the_selected_model(client, adm):
    models = train(client, adm.h, activate_best=True).get_json()["models"]
    active = [m for m in client.get("/api/ml/models", headers=adm.h).get_json()["models"] if m["is_active"]]
    selected = [m for m in models if m["selected_in_run"]]
    assert len(active) == 1 and active[0]["id"] == selected[0]["id"]


def test_prediction_logs_and_performance_endpoints(client, adm, make_service):
    from app.extensions import db
    from app.models.queue import QueueTicket
    from app.models.user import User
    svc = make_service()
    cust = User.query.filter_by(email="cust@example.com").one()
    t = QueueTicket(queue_number="GEN-001", user_id=cust.id, service_id=svc.id, queue_date=__import__("datetime").date(2026, 3, 2),
                    sequence=1, status="WAITING")
    db.session.add(t)
    db.session.flush()
    for i, (p, a) in enumerate(((10, 12), (20, 18), (30, 33))):
        db.session.add(PredictionLog(queue_ticket_id=t.id, source="fallback", prediction=p, actual_value=a if i < 2 else None,
                                     prediction_error=(p - a) if i < 2 else None, features={"people_ahead": i}))
    db.session.commit()
    logs = client.get("/api/ml/prediction-logs?per_page=2", headers=adm.h).get_json()
    assert logs["total"] == 3 and logs["pages"] == 2 and len(logs["logs"]) == 2 and logs["logs"][0]["queue_number"] == "GEN-001"
    assert client.get("/api/ml/prediction-logs?with_actual=true", headers=adm.h).get_json()["total"] == 2
    assert client.get("/api/ml/prediction-logs?page=x", headers=adm.h).status_code == 400
    perf = client.get("/api/ml/performance", headers=adm.h).get_json()
    fb = perf["groups"][0]
    assert fb["n"] == 2 and fb["mae"] == 2.0 and perf["predictions_awaiting_outcome"] == 1


# ------------------------------------------------------------------ CLI
def test_cli_generates_reproducible_dataset(app, tmp_path):
    runner = app.test_cli_runner()
    out1, out2 = tmp_path / "a.csv", tmp_path / "b.csv"
    for out in (out1, out2):
        res = runner.invoke(args=["ml-generate-data", "--rows", "250", "--seed", "9", "--out", str(out)])
        assert res.exit_code == 0 and "250" in res.output
    assert out1.read_bytes() == out2.read_bytes()
    rows = list(csv.DictReader(out1.open()))
    assert len(rows) == 250 and "waiting_time" in rows[0]


def test_cli_train_prints_comparison_and_can_activate(app):
    res = app.test_cli_runner().invoke(args=["ml-train", "--rows", "600", "--seed", "4", "--activate-best"])
    assert res.exit_code == 0, res.output
    for name in ("Linear Regression", "Random Forest", "Gradient Boosting", "Baseline", "SELECTED", "ACTIVE", "held-out"):
        assert name in res.output
    assert ml_service.active_model_version() is not None
    bad = app.test_cli_runner().invoke(args=["ml-train", "--source", "historical"])
    assert bad.exit_code != 0
