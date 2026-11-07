from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.extensions import db
from app.models.counter import Counter, CounterSession, StaffCounterAssignment
from app.models.service import Service

from .helpers import add_ticket


@pytest.fixture()
def r(client, make_user, make_service, make_counter, login):
    gen = make_service()
    staff1, staff2 = make_user("STAFF", "s1@example.com"), make_user("STAFF", "s2@example.com")
    gone = make_user("STAFF", "gone@example.com", status="INACTIVE")
    make_user("ADMIN", "admin@example.com")
    make_user("CUSTOMER", "plain@example.com")
    c1 = make_counter("GEN 1", gen, "OPEN", [staff1])
    c2 = make_counter("GEN 2", gen, "CLOSED", [staff2])  # staffed and closed: a candidate
    make_counter("GEN 3", gen, "CLOSED")  # no staff: not a candidate
    make_counter("GEN 4", gen, "CLOSED", [gone])  # only an inactive staff member: not a candidate
    return SimpleNamespace(gen=gen, c1=c1, c2=c2, mk=make_user, mc=make_counter, svc=make_service, staff2=staff2,
                           h=login("admin@example.com"), hc=login("plain@example.com"))


def waiting(r, n, service=None):
    for _ in range(n):
        add_ticket(r.mk, service or r.gen, "WAITING", join=datetime.now(timezone.utc) - timedelta(hours=5))  # old: outside the arrival window


def recs(client, r):
    res = client.get("/api/analytics/recommendations", headers=r.h)
    assert res.status_code == 200
    return {x["service"]["prefix"]: x for x in res.get_json()["recommendations"]}


# ------------------------------------------------------------------ no action
def test_quiet_queue_needs_no_action_and_says_why(client, r):
    waiting(r, 2)
    rec = recs(client, r)["GEN"]
    assert rec["action"] == "NONE" and rec["priority"] == "NONE" and rec["suggested_additional_counters"] == 0
    assert rec["headline"] == "No action needed for General Enquiry."
    text = " ".join(rec["reasons"])
    assert "2 customers are waiting" in text and "20 minutes" in text and "below the 30-minute threshold" in text
    assert rec["data"]["waiting"] == 2 and rec["data"]["estimated_wait"] == 20.0 and rec["data"]["counters"]["open"] == 1


# ------------------------------------------------------------------ high congestion
def test_high_congestion_recommends_a_counter_with_real_numbers(client, r):
    waiting(r, 12)
    rec = recs(client, r)["GEN"]
    assert rec["action"] == "OPEN_COUNTER" and rec["priority"] == "HIGH"
    assert rec["headline"] == ("High congestion detected. 12 customers are waiting, the estimated waiting time is 120 minutes, "
                               "and 1 counter is active. Consider opening 1 additional counter.")
    assert [c["name"] for c in rec["candidate_counters"]] == ["GEN 2"]  # only the staffed, closed counter
    reasons = " ".join(rec["reasons"])
    assert "HIGH starts at 11 waiting" in reasons and "about 120 minutes" in reasons and "alert threshold is 30 minutes" in reasons
    assert "Closed counter with assigned staff: GEN 2" in reasons
    assert "busy" not in reasons  # the open counter is free (no customer at it), so that reason must not appear


def test_critical_congestion_is_urgent_and_suggests_two_when_two_are_available(client, r):
    waiting(r, 21)
    one = recs(client, r)["GEN"]
    assert one["priority"] == "URGENT" and one["suggested_additional_counters"] == 1  # capped by the single candidate
    assert one["headline"].startswith("Critical congestion detected. 21 customers are waiting")
    db.session.add(StaffCounterAssignment(staff_id=r.mk("STAFF", "s3@example.com").id, counter_id=db.session.query(Counter).filter_by(name="GEN 3").one().id))
    db.session.commit()
    two = recs(client, r)["GEN"]
    assert two["suggested_additional_counters"] == 2 and "Consider opening 2 additional counters." in two["headline"]


# ------------------------------------------------------------------ individual rules
def test_no_open_counter_while_customers_wait_is_urgent(client, r):
    r.c1.status = "CLOSED"
    db.session.commit()
    waiting(r, 3)
    rec = recs(client, r)["GEN"]
    assert rec["priority"] == "URGENT" and rec["data"]["estimated_wait"] is None and rec["data"]["estimate_source"] == "unavailable"
    assert rec["headline"] == "3 customers are waiting and no counter is open. Consider opening 1 additional counter."
    assert "No counter is open for this service while 3 customers are waiting." in rec["reasons"]


def test_no_open_counter_and_nobody_waiting_is_not_an_emergency(client, r):
    r.c1.status = "CLOSED"
    db.session.commit()
    assert recs(client, r)["GEN"]["action"] == "NONE"


def test_long_estimated_wait_alone_triggers_a_recommendation(client, r):
    r.gen.default_service_duration = 50  # 3 ahead x 50 min on one counter = 150 minutes, yet only LOW congestion
    db.session.commit()
    waiting(r, 3)
    rec = recs(client, r)["GEN"]
    assert rec["data"]["congestion"] == "LOW" and rec["action"] == "OPEN_COUNTER" and rec["priority"] == "HIGH"  # >= 2x the threshold
    assert len(rec["reasons"]) == 2 and "about 150 minutes" in rec["reasons"][0]  # the wait rule plus the staffed counter
    assert not any("congestion" in x.lower() for x in rec["reasons"])  # congestion is LOW, so it is not cited


def test_arrivals_outpacing_capacity_triggers_a_recommendation(client, r):
    now = datetime.now(timezone.utc)
    for _ in range(6):  # 8 joins in the last 30 minutes = 16/hour; one counter serves 60/10 = 6/hour
        add_ticket(r.mk, r.gen, "COMPLETED", join=now - timedelta(minutes=10), service_duration=10.0)
    waiting_tickets = [add_ticket(r.mk, r.gen, "WAITING", join=now - timedelta(minutes=5)) for _ in range(2)]
    rec = recs(client, r)["GEN"]
    assert len(waiting_tickets) == 2 and rec["action"] == "OPEN_COUNTER" and rec["priority"] == "MEDIUM"
    assert rec["data"]["arrival_rate_per_hour"] == 16.0 and rec["data"]["offered_load"] == 2.67
    assert any("arriving at about 16 per hour" in x and "about 6 per hour" in x for x in rec["reasons"])


def test_old_arrivals_do_not_count_toward_the_arrival_rate(client, r):
    waiting(r, 2)  # joined 5 hours ago: outside the 30-minute window
    assert recs(client, r)["GEN"]["data"]["arrival_rate_per_hour"] == 0.0


# ------------------------------------------------------------------ staff availability
def test_without_a_staffed_closed_counter_the_advice_is_to_assign_staff(client, r):
    db.session.query(StaffCounterAssignment).filter_by(counter_id=r.c2.id).delete()
    db.session.commit()
    waiting(r, 12)
    rec = recs(client, r)["GEN"]
    assert rec["candidate_counters"] == [] and rec["suggested_additional_counters"] == 0
    assert rec["headline"].endswith("Consider assigning staff to another counter for this service.")
    assert "No closed counter with an active assigned staff member is available for this service." in rec["reasons"]


def test_deactivated_staff_do_not_make_a_counter_a_candidate(client, r):
    waiting(r, 12)
    assert "GEN 4" not in [c["name"] for c in recs(client, r)["GEN"]["candidate_counters"]]
    assert "GEN 3" not in [c["name"] for c in recs(client, r)["GEN"]["candidate_counters"]]


# ------------------------------------------------------------------ configuration & consistency
def test_thresholds_are_configurable(client, r):
    waiting(r, 2)  # estimate 20 minutes
    assert recs(client, r)["GEN"]["action"] == "NONE"
    client.patch("/api/settings", json={"settings": {"recommendations.wait_threshold_minutes": 15}}, headers=r.h)
    rec = recs(client, r)["GEN"]
    assert rec["action"] == "OPEN_COUNTER" and "alert threshold is 15 minutes" in " ".join(rec["reasons"])
    client.patch("/api/settings", json={"settings": {"recommendations.wait_threshold_minutes": None, "congestion.moderate_min": 1, "congestion.high_min": 2, "congestion.critical_min": 3}}, headers=r.h)
    assert "HIGH starts at 2 waiting" in " ".join(recs(client, r)["GEN"]["reasons"])


def test_congestion_level_matches_the_dashboard(client, r):
    waiting(r, 11)
    rec = recs(client, r)["GEN"]
    dash = {s["prefix"]: s for s in client.get("/api/admin/dashboard", headers=r.h).get_json()["services"]}
    assert rec["data"]["congestion"] == dash["GEN"]["congestion"] == "HIGH"  # 11 is the inclusive HIGH boundary


def test_services_are_ordered_by_urgency_and_inactive_ones_are_ignored(client, r):
    pay = r.svc("Payments", "PAY", 6)
    r.mc("PAY 1", pay, "OPEN")
    old = r.svc("Retired", "OLD", status="INACTIVE")
    waiting(r, 1, pay)
    waiting(r, 12)
    waiting(r, 5, old)
    out = client.get("/api/analytics/recommendations", headers=r.h).get_json()["recommendations"]
    assert [x["service"]["prefix"] for x in out] == ["GEN", "PAY"]
    assert out[0]["priority"] == "HIGH" and out[1]["priority"] == "NONE"


# ------------------------------------------------------------------ advisory only
def test_recommendations_change_nothing_and_make_no_promises(client, r):
    waiting(r, 25)
    sessions_before = CounterSession.query.count()
    out = client.get("/api/analytics/recommendations", headers=r.h).get_json()["recommendations"][0]
    assert db.session.get(Counter, r.c2.id).status == "CLOSED" and CounterSession.query.count() == sessions_before
    text = (out["headline"] + " " + " ".join(out["reasons"])).lower()
    for promise in ("will reduce", "will fall", "will drop", "guarantee", "reduce the wait"):
        assert promise not in text


def test_recommendations_are_admin_only(client, r):
    assert client.get("/api/analytics/recommendations").status_code == 401
    assert client.get("/api/analytics/recommendations", headers=r.hc).status_code == 403
