from datetime import date, datetime, timedelta, timezone

import pytest

from app.extensions import db
from app.models.counter import CounterSession
from app.models.ml import ModelVersion, PredictionLog
from app.services import analytics_service as an
from app.services.queue_service import QueueError

from .helpers import add_ticket, local, utc

D1, D2, D3 = date(2026, 3, 2), date(2026, 3, 3), date(2026, 3, 4)


@pytest.fixture()
def a(client, make_user, make_service, make_counter, login):
    gen, pay = make_service(), make_service("Payments", "PAY", 6)
    staff = make_user("STAFF", "staff@example.com")
    make_user("ADMIN", "admin@example.com")
    make_user("CUSTOMER", "plain@example.com")
    c1 = make_counter("GEN 1", gen, "OPEN", [staff])
    return type("A", (), dict(gen=gen, pay=pay, c1=c1, mk=make_user, h=login("admin@example.com"), hs=login("staff@example.com"), hc=login("plain@example.com")))


# ------------------------------------------------------------------ permissions & range validation
ENDPOINTS = ["queue-length", "waiting-by-hour", "daily-volume", "service-performance", "counter-utilization", "prediction-accuracy", "recommendations"]


@pytest.mark.parametrize("name", ENDPOINTS)
def test_analytics_are_admin_only(client, a, name):
    url = f"/api/analytics/{name}"
    assert client.get(url).status_code == 401
    assert client.get(url, headers=a.hs).status_code == 403
    assert client.get(url, headers=a.hc).status_code == 403
    assert client.get(url, headers=a.h).status_code == 200


@pytest.mark.parametrize("query", ["days=0", "days=abc", "days=-3", "from=2026-03-05&to=2026-03-01", "from=nope", "to=2026-13-40", "from=2026-01-01&to=2026-06-01"])
def test_bad_ranges_are_rejected(client, a, query):
    assert client.get(f"/api/analytics/daily-volume?{query}", headers=a.h).status_code == 400


def test_range_parsing(app):
    assert an.parse_range({"from": "2026-03-02", "to": "2026-03-04"}) == (D1, D3)
    start, end = an.parse_range({"days": "3"})
    assert (end - start).days == 2
    assert an.parse_range({"from": "2026-03-02", "to": "2026-03-02"}) == (D1, D1)
    with pytest.raises(QueueError):
        an.parse_range({"from": "2026-01-01", "to": "2026-04-01"})  # 91 days


def test_bad_service_filter_and_hours(client, a):
    assert client.get("/api/analytics/daily-volume?service_id=x", headers=a.h).status_code == 400
    for hours in ("0", "169", "x"):
        assert client.get(f"/api/analytics/queue-length?hours={hours}", headers=a.h).status_code == 400


# ------------------------------------------------------------------ queue length over time
def test_queue_length_is_reconstructed_from_join_and_leave_times(app, a):
    now = utc(2026, 3, 2, 12, 0)
    add_ticket(a.mk, a.gen, "CALLED", join=now - timedelta(hours=3), called_time=now - timedelta(hours=1), wait_ended_time=now - timedelta(hours=1))
    add_ticket(a.mk, a.gen, "WAITING", join=now - timedelta(hours=2))
    add_ticket(a.mk, a.gen, "CANCELLED", join=now - timedelta(minutes=90), wait_ended_time=now - timedelta(minutes=30))
    add_ticket(a.mk, a.gen, "CANCELLED", join=now - timedelta(hours=2))  # legacy: leave time unknown -> excluded
    add_ticket(a.mk, a.pay, "WAITING", join=now - timedelta(hours=1))
    series = an.queue_length_series(hours=3, now=now)
    assert [p["waiting"] for p in series["points"]] == [1, 2, 3, 2]  # at -3h, -2h, -1h (+PAY), now
    assert [p["peak"] for p in series["points"]] == [1, 2, 3, 3]  # highest count at any moment in the hour ending there
    assert series["peak"] == 3 and series["hours"] == 3 and len(series["points"]) == 4
    only_gen = an.queue_length_series(hours=3, service_id=a.gen.id, now=now)
    assert [p["waiting"] for p in only_gen["points"]] == [1, 2, 2, 1]
    assert [p["peak"] for p in only_gen["points"]] == [1, 2, 3, 2]
    assert series["points"][-1]["time"].startswith("2026-03-02T12:00")
    assert series["points"][-1]["label"] == "15:00"  # local time


def test_a_spike_between_hour_boundaries_is_not_missed(app, a):
    now = utc(2026, 3, 2, 12, 0)
    for _ in range(4):  # four customers join 40 minutes ago and all cancel 20 minutes ago: invisible at the boundaries
        add_ticket(a.mk, a.gen, "CANCELLED", join=now - timedelta(minutes=40), wait_ended_time=now - timedelta(minutes=20))
    series = an.queue_length_series(hours=1, now=now)
    assert [p["waiting"] for p in series["points"]] == [0, 0]
    assert [p["peak"] for p in series["points"]] == [0, 4] and series["peak"] == 4


def test_peaks_match_a_minute_by_minute_count(app, a):
    now = utc(2026, 3, 2, 12, 0)
    spec = [(350, 300), (340, 120), (200, 190), (185, 61), (130, 60), (125, None), (62, 59), (61, 61), (45, 30), (31, None), (10, 5), (330, 61)]  # (joined, left) minutes ago
    for joined, left in spec:
        add_ticket(a.mk, a.gen, "WAITING" if left is None else "CALLED", join=now - timedelta(minutes=joined),
                   **({} if left is None else {"wait_ended_time": now - timedelta(minutes=left), "called_time": now - timedelta(minutes=left)}))
    spans = [(-j, None if left is None else -left) for j, left in spec]  # minutes relative to now
    count = lambda t: sum(1 for j, e in spans if j <= t and (e is None or e > t))  # noqa: E731
    points = an.queue_length_series(hours=6, now=now)["points"]
    for i, p in enumerate(points):
        end = -60 * (6 - i)
        assert p["waiting"] == count(end)
        expected_peak = count(end) if i == 0 else max(count(t) for t in range(end - 60, end + 1))
        assert p["peak"] == expected_peak, (i, p)
        assert p["peak"] >= p["waiting"]


def test_queue_length_api_ends_with_the_current_waiting_count(client, a):
    for _ in range(3):
        add_ticket(a.mk, a.gen, "WAITING", join=datetime.now(timezone.utc) - timedelta(minutes=5))
    res = client.get("/api/analytics/queue-length?hours=6", headers=a.h).get_json()
    assert len(res["points"]) == 7 and res["points"][-1]["waiting"] == 3 and res["points"][0]["waiting"] == 0


# ------------------------------------------------------------------ waiting time by hour
def test_waiting_by_hour_groups_by_local_join_hour(client, a):
    add_ticket(a.mk, a.gen, "COMPLETED", join=local(2026, 3, 2, 9, 10), actual_waiting_time=10.0)
    add_ticket(a.mk, a.gen, "COMPLETED", join=local(2026, 3, 2, 9, 50), actual_waiting_time=20.0)
    add_ticket(a.mk, a.gen, "COMPLETED", join=local(2026, 3, 3, 14, 0), actual_waiting_time=30.0)
    add_ticket(a.mk, a.gen, "CANCELLED", join=local(2026, 3, 2, 9, 30))  # never measured
    add_ticket(a.mk, a.gen, "COMPLETED", join=local(2026, 3, 9, 9, 0), actual_waiting_time=99.0)  # outside the range
    res = client.get("/api/analytics/waiting-by-hour?from=2026-03-02&to=2026-03-04", headers=a.h).get_json()
    hours = {h["hour"]: h for h in res["hours"]}
    assert len(res["hours"]) == 24 and res["measured"] == 3
    assert hours[9]["avg_waiting"] == 15.0 and hours[9]["n"] == 2
    assert hours[14]["avg_waiting"] == 30.0 and hours[14]["n"] == 1
    assert hours[10]["avg_waiting"] is None and hours[10]["n"] == 0  # no data is null, not 0


# ------------------------------------------------------------------ daily volume & outcomes
def test_daily_volume_counts_outcomes_by_local_day(client, a):
    add_ticket(a.mk, a.gen, "COMPLETED", join=local(2026, 3, 2, 23, 30))  # late evening: day 1 locally (20:30 UTC)
    add_ticket(a.mk, a.gen, "CANCELLED", join=local(2026, 3, 3, 0, 30))  # just after midnight local: day 2 (21:30 UTC on day 1)
    add_ticket(a.mk, a.gen, "SKIPPED", join=local(2026, 3, 3, 10, 0))
    add_ticket(a.mk, a.pay, "ABSENT", join=local(2026, 3, 3, 11, 0))
    add_ticket(a.mk, a.pay, "WAITING", join=local(2026, 3, 3, 12, 0))
    add_ticket(a.mk, a.pay, "SERVING", join=local(2026, 3, 3, 12, 5))
    res = client.get("/api/analytics/daily-volume?from=2026-03-02&to=2026-03-04", headers=a.h).get_json()
    days = {d["date"]: d for d in res["days"]}
    assert list(days) == ["2026-03-02", "2026-03-03", "2026-03-04"]
    assert (days["2026-03-02"]["joined"], days["2026-03-02"]["completed"]) == (1, 1)
    d2 = days["2026-03-03"]
    assert (d2["joined"], d2["cancelled"], d2["skipped"], d2["absent"], d2["in_progress"], d2["completed"]) == (5, 1, 1, 1, 2, 0)
    assert days["2026-03-04"]["joined"] == 0  # empty days are present with zeros
    assert res["totals"] == {"joined": 6, "completed": 1, "cancelled": 1, "skipped": 1, "absent": 1, "in_progress": 2}
    only_pay = client.get(f"/api/analytics/daily-volume?from=2026-03-02&to=2026-03-04&service_id={a.pay.id}", headers=a.h).get_json()
    assert only_pay["totals"]["joined"] == 3


# ------------------------------------------------------------------ service performance
def test_service_performance_is_computed_per_service(client, a, make_service):
    make_service("Retired", "OLD", status="INACTIVE")
    for wait, dur in ((10.0, 4.0), (20.0, 8.0)):
        add_ticket(a.mk, a.gen, "COMPLETED", join=local(2026, 3, 2, 9), actual_waiting_time=wait, service_duration=dur)
    add_ticket(a.mk, a.gen, "CANCELLED", join=local(2026, 3, 2, 10))
    add_ticket(a.mk, a.gen, "SKIPPED", join=local(2026, 3, 2, 11))
    add_ticket(a.mk, a.gen, "ABSENT", join=local(2026, 3, 2, 12))
    add_ticket(a.mk, a.pay, "COMPLETED", join=local(2026, 3, 2, 9), actual_waiting_time=5.0, service_duration=3.0)
    rows = {r["prefix"]: r for r in client.get("/api/analytics/service-performance?from=2026-03-02&to=2026-03-02", headers=a.h).get_json()["services"]}
    assert set(rows) == {"GEN", "PAY"}  # inactive service without tickets is omitted
    g = rows["GEN"]
    assert (g["joined"], g["completed"], g["cancelled"], g["skipped"], g["absent"]) == (5, 2, 1, 1, 1)
    assert g["completion_rate"] == 0.4 and g["avg_waiting"] == 15.0 and g["max_waiting"] == 20.0 and g["avg_service_duration"] == 6.0
    assert rows["PAY"]["completion_rate"] == 1.0 and rows["PAY"]["avg_service_duration"] == 3.0


def test_service_with_no_tickets_has_null_not_zero_rates(client, a):
    row = next(r for r in client.get("/api/analytics/service-performance?from=2026-03-02&to=2026-03-02", headers=a.h).get_json()["services"] if r["prefix"] == "GEN")
    assert row["joined"] == 0 and row["completion_rate"] is None and row["avg_waiting"] is None and row["avg_service_duration"] is None


# ------------------------------------------------------------------ counter utilization
def session(counter, opened, closed=None):
    db.session.add(CounterSession(counter_id=counter.id, opened_at=opened, closed_at=closed))
    db.session.commit()


def serve(a, counter, start, minutes):
    return add_ticket(a.mk, a.gen, "COMPLETED", join=start - timedelta(minutes=5), counter_id=counter.id, service_start_time=start,
                      service_end_time=start + timedelta(minutes=minutes), service_duration=float(minutes), actual_waiting_time=5.0)


def test_utilization_is_serving_time_over_open_time(app, a):
    session(a.c1, local(2026, 3, 2, 8), local(2026, 3, 2, 12))  # open 240 minutes
    serve(a, a.c1, local(2026, 3, 2, 9), 60)
    serve(a, a.c1, local(2026, 3, 2, 10), 30)
    serve(a, a.c1, local(2026, 3, 2, 13), 30)  # outside any open session: not counted as busy time
    row = an.counter_utilization(date(2026, 3, 2), date(2026, 3, 2))["counters"][0]
    assert row["open_minutes"] == 240.0 and row["serving_minutes"] == 90.0 and row["utilization"] == 0.375
    assert row["customers_served"] == 3 and row["avg_service_duration"] == 40.0 and row["service"] == "General Enquiry"


def test_open_session_runs_until_now_and_sessions_are_clipped_to_the_range(app, a):
    session(a.c1, local(2026, 3, 1, 22), local(2026, 3, 2, 2))  # 2 of its 4 hours fall on 2 March
    session(a.c1, local(2026, 3, 2, 8))  # still open
    row = an.counter_utilization(date(2026, 3, 2), date(2026, 3, 2), now=local(2026, 3, 2, 10))["counters"][0]
    assert row["open_minutes"] == 120 + 120  # 00:00-02:00 plus 08:00-10:00


def test_counter_without_recorded_sessions_reports_null_utilization(client, a):
    serve(a, a.c1, local(2026, 3, 2, 9), 30)
    row = client.get("/api/analytics/counter-utilization?from=2026-03-02&to=2026-03-02", headers=a.h).get_json()["counters"][0]
    assert row["open_minutes"] == 0 and row["utilization"] is None and row["customers_served"] == 1


# ------------------------------------------------------------------ prediction accuracy
def logs(a, rows, mv=None):
    t = add_ticket(a.mk, a.gen, "COMPLETED", join=local(2026, 3, 2, 9))
    for day, pred, actual, source in rows:
        db.session.add(PredictionLog(queue_ticket_id=t.id, model_version_id=mv.id if mv else None, source=source, prediction=pred,
                                     actual_value=actual, prediction_error=None if actual is None else round(pred - actual, 2),
                                     features={}, created_at=local(2026, 3, day, 10)))
    db.session.commit()


def test_prediction_accuracy_metrics_trend_and_points(client, a):
    mv = ModelVersion(model_name="Random Forest", version="1.0", run_id="r", model_path="x", data_source="synthetic", details={})
    db.session.add(mv)
    db.session.commit()
    logs(a, [(2, 10.0, 12.0, "machine_learning"), (2, 20.0, 18.0, "machine_learning"), (3, 30.0, 33.0, "machine_learning"), (3, 40.0, None, "machine_learning")], mv)
    logs(a, [(3, 10.0, 20.0, "fallback"), (4, 50.0, 40.0, "fallback")])
    res = client.get("/api/analytics/prediction-accuracy?from=2026-03-02&to=2026-03-04", headers=a.h).get_json()
    groups = {g["source"]: g for g in res["groups"]}
    ml = groups["machine_learning"]
    assert ml["n"] == 3 and ml["model"] == "Random Forest 1.0" and ml["mae"] == pytest.approx(2.3333, abs=1e-4)
    assert ml["r2"] is None and res["overall"]["r2"] is None  # R-squared needs at least 10 measured predictions
    assert ml["rmse"] == pytest.approx(((4 + 4 + 9) / 3) ** 0.5, abs=1e-3)
    assert groups["fallback"]["n"] == 2 and groups["fallback"]["mae"] == 10.0 and groups["fallback"]["model"] is None
    assert res["overall"]["n"] == 5 and res["awaiting_outcome"] == 1 and len(res["points"]) == 5
    trend = {t["date"]: t for t in res["trend"]}
    assert trend["2026-03-02"]["n"] == 2 and trend["2026-03-02"]["mae"] == 2.0 and trend["2026-03-02"]["bias"] == 0.0  # errors -2 and +2
    assert trend["2026-03-03"]["n"] == 2 and trend["2026-03-03"]["mae"] == 6.5 and trend["2026-03-03"]["bias"] == -6.5  # -3 and -10
    assert "positive means customers were told longer" in res["note"]


def test_r2_appears_only_with_enough_measured_predictions(client, a):
    nine = [(2, 10.0 + i, 10.0 + i + (1 if i % 2 else -1), "fallback") for i in range(9)]
    logs(a, nine)
    first = client.get("/api/analytics/prediction-accuracy?from=2026-03-02&to=2026-03-04", headers=a.h).get_json()["overall"]
    assert first["n"] == 9 and first["mae"] == 1.0 and first["r2"] is None
    logs(a, [(2, 20.0, 21.0, "fallback")])
    tenth = client.get("/api/analytics/prediction-accuracy?from=2026-03-02&to=2026-03-04", headers=a.h).get_json()["overall"]
    assert tenth["n"] == 10 and tenth["r2"] is not None and 0.5 < tenth["r2"] <= 1  # a meaningful value once there is enough data


def test_prediction_accuracy_with_one_or_no_outcomes_never_invents_numbers(client, a):
    empty = client.get("/api/analytics/prediction-accuracy?from=2026-03-02&to=2026-03-04", headers=a.h).get_json()
    assert empty["overall"] == {"n": 0, "mae": None, "rmse": None, "r2": None} and empty["trend"] == [] and empty["points"] == []
    logs(a, [(2, 10.0, 14.0, "fallback")])
    one = client.get("/api/analytics/prediction-accuracy?from=2026-03-02&to=2026-03-04", headers=a.h).get_json()["overall"]
    assert one["n"] == 1 and one["mae"] == 4.0 and one["r2"] is None  # R-squared is undefined for a single point
