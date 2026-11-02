from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.extensions import db
from app.ml.synthetic import generate_dataset
from app.ml.training import predict_minutes
from app.models.ml import ModelVersion, PredictionLog
from app.models.queue import QueueTicket
from app.services import ml_service, prediction_service, staff_service
from app.services.queue_service import QueueError

T0 = datetime(2026, 3, 2, 9, 0, 0, tzinfo=timezone.utc)


@pytest.fixture()
def w(client, make_user, make_service, make_counter, login):
    gen = make_service()
    staff = make_user("STAFF", "staff@example.com")
    counter = make_counter("Counter 1", gen, "OPEN", [staff])
    custs = [make_user("CUSTOMER", f"c{i}@example.com") for i in range(4)]
    make_user("ADMIN", "admin@example.com")
    return SimpleNamespace(
        gen=gen, staff=staff, counter=counter, hs=login("staff@example.com"), ha=login("admin@example.com"),
        hc=[login(u.email) for u in custs],
    )


def join(client, h, sid):
    res = client.post("/api/queue/join", json={"service_id": sid}, headers=h)
    assert res.status_code == 201, res.get_json()
    return res.get_json()["ticket"]


def train_and_activate(rows=600, seed=5):
    versions = ml_service.train_run("synthetic", rows, seed)
    best = next(v for v in versions if v.details["selected_in_run"])
    return ml_service.activate(best.id)


# ------------------------------------------------------------------ fallback & unavailable
def test_without_a_model_the_documented_fallback_is_used_and_labelled(client, w):
    first = join(client, w.hc[0], w.gen.id)
    assert first["prediction"]["source"] == "fallback" and first["prediction"]["reason"] == "no_active_model"
    assert first["predicted_waiting_time"] == 0.0  # nobody ahead
    second = join(client, w.hc[1], w.gen.id)
    assert second["predicted_waiting_time"] == 10.0  # 1 person ahead / 1 open counter x 10 min default duration
    logs = PredictionLog.query.order_by(PredictionLog.id).all()
    assert [l.source for l in logs] == ["fallback", "fallback"] and all(l.model_version_id is None for l in logs)
    f = logs[1].features
    assert (f["people_ahead"], f["queue_length"], f["active_counters"], f["busy_counters"]) == (1, 2, 1, 0)
    assert f["service_type"] == "GEN" and f["average_service_duration"] == 10.0 and f["staff_count"] == 1


def test_no_open_counter_means_no_estimate_not_a_made_up_one(client, w):
    w.counter.status = "CLOSED"
    db.session.commit()
    t = join(client, w.hc[0], w.gen.id)
    assert t["predicted_waiting_time"] is None
    assert t["prediction"] == {"minutes": None, "source": "unavailable", "model": None, "model_version": None, "reason": "no_open_counters"}
    assert PredictionLog.query.count() == 0


def test_busy_counters_and_recent_durations_feed_the_features(client, w, make_user):
    # a completed ticket with a 20-minute service sets the "recent average duration"
    other = make_user("CUSTOMER", "done@example.com")
    db.session.add(QueueTicket(queue_number="GEN-900", user_id=other.id, service_id=w.gen.id, counter_id=w.counter.id,
                               queue_date=T0.date(), sequence=900, status="COMPLETED", service_duration=20.0,
                               service_end_time=T0))
    db.session.commit()
    join(client, w.hc[0], w.gen.id)
    client.post(f"/api/staff/counters/{w.counter.id}/call-next", headers=w.hs)  # counter becomes busy
    t = join(client, w.hc[1], w.gen.id)
    f = PredictionLog.query.filter_by(queue_ticket_id=t["id"]).one().features
    assert f["busy_counters"] == 1 and f["average_service_duration"] == 20.0
    # the first customer was called, so has left the waiting line: nobody is ahead of the new ticket
    assert f["people_ahead"] == 0 and f["queue_length"] == 1
    assert t["predicted_waiting_time"] == 0.0


# ------------------------------------------------------------------ trained model
def test_active_model_produces_the_prediction_and_it_is_logged(client, w, fast_models):
    mv = train_and_activate()
    join(client, w.hc[0], w.gen.id)
    t = join(client, w.hc[1], w.gen.id)
    assert t["prediction"]["source"] == "machine_learning"
    assert t["prediction"]["model"] == mv.model_name and t["prediction"]["model_version"] == mv.version
    log = PredictionLog.query.filter_by(queue_ticket_id=t["id"]).one()
    assert log.source == "machine_learning" and log.model_version_id == mv.id and log.actual_value is None
    # the stored number really is the model's output for the logged features
    direct = round(predict_minutes(ml_service.load_pipeline(mv), log.features), 1)
    assert t["predicted_waiting_time"] == direct == log.prediction


def test_broken_model_file_degrades_to_fallback_without_blocking_joins(client, w, fast_models):
    mv = train_and_activate()
    ml_service.resolve_artifact(mv.model_path).unlink()
    ml_service.clear_model_cache()
    t = join(client, w.hc[0], w.gen.id)
    assert t["prediction"]["source"] == "fallback" and t["prediction"]["reason"] == "model_unavailable"


def test_prediction_failure_never_blocks_joining(client, w, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("feature store down")
    monkeypatch.setattr(prediction_service, "build_features", boom)
    res = client.post("/api/queue/join", json={"service_id": w.gen.id}, headers=w.hc[0])
    assert res.status_code == 201
    assert res.get_json()["ticket"]["predicted_waiting_time"] is None and res.get_json()["ticket"]["prediction"] is None


# ------------------------------------------------------------------ recording actual outcomes
def test_actual_wait_is_stored_next_to_the_original_prediction(client, w, monkeypatch):
    a = join(client, w.hc[0], w.gen.id)
    b = join(client, w.hc[1], w.gen.id)  # predicted 10.0 by the fallback
    QueueTicket.query.filter_by(id=a["id"]).update({"join_time": T0})
    db.session.commit()
    clock = {"t": T0 + timedelta(minutes=1)}
    monkeypatch.setattr(staff_service, "_now", lambda: clock["t"])
    client.post(f"/api/staff/counters/{w.counter.id}/call-next", headers=w.hs)
    clock["t"] = T0 + timedelta(minutes=9, seconds=30)
    client.post(f"/api/staff/tickets/{a['id']}/start", headers=w.hs)
    log_a = PredictionLog.query.filter_by(queue_ticket_id=a["id"]).one()
    assert log_a.actual_value == 9.5 and log_a.prediction_error == round(log_a.prediction - 9.5, 2)
    assert db.session.get(QueueTicket, a["id"]).actual_waiting_time == 9.5
    # the second ticket has not started, so its outcome is still unknown
    assert PredictionLog.query.filter_by(queue_ticket_id=b["id"]).one().actual_value is None
    # cancelled tickets never receive an outcome
    client.post(f"/api/queue/tickets/{b['id']}/cancel", headers=w.hc[1])
    assert PredictionLog.query.filter_by(queue_ticket_id=b["id"]).one().actual_value is None


def test_live_performance_is_computed_from_real_logs(client, w):
    t = join(client, w.hc[0], w.gen.id)
    for pred, actual in ((10, 12), (20, 18), (30, 33)):
        db.session.add(PredictionLog(queue_ticket_id=t["id"], source="fallback", prediction=pred, actual_value=actual,
                                     prediction_error=pred - actual, features={}))
    db.session.commit()
    perf = ml_service.live_performance()
    fb = next(g for g in perf["groups"] if g["source"] == "fallback")
    assert fb["n"] == 3 and fb["mae"] == pytest.approx(2.3333, abs=1e-4)
    assert fb["rmse"] == pytest.approx(((4 + 4 + 9) / 3) ** 0.5, abs=1e-3)
    assert perf["predictions_awaiting_outcome"] == 1  # the join-time log has no outcome yet


# ------------------------------------------------------------------ prediction API
def post_pred(client, h, **body):
    return client.post("/api/predictions/waiting-time", json=body, headers=h)


def test_prediction_endpoint_derives_features_from_trusted_state(client, w):
    join(client, w.hc[0], w.gen.id)
    join(client, w.hc[1], w.gen.id)
    res = post_pred(client, w.hc[2], service_id=w.gen.id)
    assert res.status_code == 200
    body = res.get_json()
    assert body["source"] == "fallback" and body["scenario"] is False
    assert body["features"]["people_ahead"] == 2 and body["features"]["queue_length"] == 3  # a new joiner would be 3rd
    assert body["predicted_waiting_time"] == 20.0
    assert PredictionLog.query.count() == 2  # ad-hoc requests are not logged against tickets


def test_customers_cannot_supply_their_own_feature_values(client, w):
    assert post_pred(client, w.hc[0], service_id=w.gen.id, people_ahead=0, queue_length=1).status_code == 403


def test_staff_can_run_what_if_scenarios_and_values_are_validated(client, w):
    low = post_pred(client, w.hs, service_id=w.gen.id, people_ahead=2, queue_length=3).get_json()
    high = post_pred(client, w.hs, service_id=w.gen.id, people_ahead=10, queue_length=11).get_json()
    assert low["scenario"] is True and high["predicted_waiting_time"] > low["predicted_waiting_time"]
    assert high["features"]["people_ahead"] == 10
    for bad in (dict(people_ahead=-1), dict(people_ahead=5, queue_length=3), dict(busy_counters=4, active_counters=1),
                dict(people_ahead="3"), dict(queue_length=1.5)):
        assert post_pred(client, w.hs, service_id=w.gen.id, **bad).status_code == 400, bad


def test_prediction_endpoint_input_and_auth_checks(client, w, make_service):
    off = make_service("Old", "OLD", status="INACTIVE")
    assert post_pred(client, w.hc[0], service_id=9999).status_code == 404
    assert post_pred(client, w.hc[0], service_id=off.id).status_code == 404
    for bad in ("1", None, True, [1]):
        assert post_pred(client, w.hc[0], service_id=bad).status_code == 400
    assert client.post("/api/predictions/waiting-time", data="x", headers=w.hc[0]).status_code == 400
    assert client.post("/api/predictions/waiting-time", json={"service_id": w.gen.id}).status_code == 401


def test_prediction_endpoint_uses_the_active_model_and_reports_unavailable(client, w, fast_models):
    mv = train_and_activate()
    body = post_pred(client, w.hc[0], service_id=w.gen.id).get_json()
    assert body["source"] == "machine_learning" and body["model"] == mv.model_name and body["model_version"] == mv.version
    w.counter.status = "CLOSED"
    db.session.commit()
    closed = post_pred(client, w.hc[0], service_id=w.gen.id).get_json()
    assert closed["predicted_waiting_time"] is None and closed["source"] == "unavailable"


# ------------------------------------------------------------------ live estimates update as the queue changes
def test_waiting_ticket_estimate_refreshes_as_people_ahead_leave(client, w):
    tickets = [join(client, h, w.gen.id) for h in w.hc[:3]]
    url = f"/api/queue/tickets/{tickets[2]['id']}"
    before = client.get(url, headers=w.hc[2]).get_json()["ticket"]
    assert before["estimated_wait"]["minutes"] == 20.0 and before["predicted_waiting_time"] == 20.0
    client.post(f"/api/queue/tickets/{tickets[0]['id']}/cancel", headers=w.hc[0])
    after = client.get(url, headers=w.hc[2]).get_json()["ticket"]
    assert after["estimated_wait"]["minutes"] == 10.0  # refreshed estimate
    assert after["predicted_waiting_time"] == 20.0  # original prediction is preserved for evaluation
    active = client.get("/api/queue/my-active", headers=w.hc[2]).get_json()["tickets"][0]
    assert active["estimated_wait"]["minutes"] == 10.0


def test_only_waiting_tickets_have_an_estimate(client, w):
    t = join(client, w.hc[0], w.gen.id)
    client.post(f"/api/queue/tickets/{t['id']}/cancel", headers=w.hc[0])
    got = client.get(f"/api/queue/tickets/{t['id']}", headers=w.hc[0]).get_json()["ticket"]
    assert got["estimated_wait"] is None


# ------------------------------------------------------------------ activation & registry safety
def test_only_one_model_can_be_active(app, fast_models):
    a = ml_service.train_run("synthetic", 600, 1)
    b = ml_service.train_run("synthetic", 600, 2)
    ml_service.activate(a[0].id)
    ml_service.activate(b[1].id)
    active = ModelVersion.query.filter_by(is_active=True).all()
    assert [m.id for m in active] == [b[1].id]
    assert b[1].version == "2.0" and a[0].version == "1.0"
    db.session.get(ModelVersion, a[0].id).is_active = True  # a second active row must be rejected by the database
    with pytest.raises(Exception):
        db.session.commit()
    db.session.rollback()


def test_ineligible_or_missing_models_cannot_be_activated(app, fast_models):
    mv = ml_service.train_run("synthetic", 600, 1)[0]
    mv.details = {**mv.details, "eligible": False}
    db.session.commit()
    with pytest.raises(QueueError) as e:
        ml_service.activate(mv.id)
    assert e.value.code == "model_ineligible"
    with pytest.raises(QueueError) as e:
        ml_service.activate(9999)
    assert e.value.status == 404


def test_model_paths_cannot_escape_the_artifact_folder(app):
    with pytest.raises(ValueError):
        ml_service.resolve_artifact("../../etc/passwd")
    with pytest.raises(ValueError):
        ml_service.resolve_artifact("/etc/passwd")
    mv = ModelVersion(model_name="Evil", version="1.0", run_id="x", model_path="../../etc/passwd", data_source="synthetic",
                      details={"eligible": True})
    db.session.add(mv)
    db.session.commit()
    with pytest.raises(QueueError) as e:
        ml_service.activate(mv.id)
    assert e.value.code == "model_unloadable"


# ------------------------------------------------------------------ historical data from the application itself
def _seed_history(client, w, n):
    t = join(client, w.hc[0], w.gen.id)
    df = generate_dataset(n, 9)
    for _, r in df.iterrows():
        created = datetime.fromisoformat(r["date"]).replace(hour=12, tzinfo=timezone.utc)
        db.session.add(PredictionLog(
            queue_ticket_id=t["id"], source="fallback", prediction=float(r["waiting_time"]) + 1.0,
            actual_value=float(r["waiting_time"]), prediction_error=1.0, created_at=created,
            features={k: (r[k].item() if hasattr(r[k], "item") else r[k]) for k in
                      ("service_type", "people_ahead", "queue_length", "active_counters", "busy_counters",
                       "average_service_duration", "staff_count", "hour", "day_of_week", "peak_hour")}))
    db.session.commit()


def test_training_on_historical_and_mixed_data(client, w, fast_models):
    _seed_history(client, w, 500)
    hist = ml_service.train_run("historical", 0, 3)
    assert {v.data_source for v in hist} == {"historical"} and hist[0].details["rows"] == 500
    mixed = ml_service.train_run("mixed", 400, 3)
    assert mixed[0].details["rows"] == 900


def test_historical_training_refuses_when_there_is_too_little_data(client, w, fast_models):
    with pytest.raises(QueueError) as e:
        ml_service.train_run("historical", 0, 3)
    assert e.value.code == "insufficient_data"
    _seed_history(client, w, 40)
    with pytest.raises(QueueError) as e:
        ml_service.train_run("historical", 0, 3)
    assert e.value.code == "insufficient_data" and "200" in e.value.message
    assert ModelVersion.query.count() == 0  # nothing half-registered
