from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.queue import QueueTicket
from app.services import staff_service

T0 = datetime(2026, 3, 2, 9, 0, 0, tzinfo=timezone.utc)


def post(client, headers, url):
    return client.post(url, headers=headers)


def join(client, headers, service_id):
    res = client.post("/api/queue/join", json={"service_id": service_id}, headers=headers)
    assert res.status_code == 201, res.get_json()
    return res.get_json()["ticket"]


def set_status(ticket_id, status):
    QueueTicket.query.filter_by(id=ticket_id).update({"status": status})
    db.session.commit()


@pytest.fixture()
def w(client, make_user, make_service, make_counter, login):
    gen = make_service()
    pay = make_service("Payments", "PAY")
    s1 = make_user("STAFF", "s1@example.com", name="Staff One")
    s2 = make_user("STAFF", "s2@example.com", name="Staff Two")
    c1 = make_counter("Counter 1", gen, "OPEN", [s1])
    c2 = make_counter("Counter 2", gen, "OPEN", [s2])
    customers = [make_user("CUSTOMER", f"cust{i}@example.com", name=f"Customer {i}") for i in range(4)]
    make_user("ADMIN", "admin@example.com")
    return SimpleNamespace(
        gen=gen, pay=pay, c1=c1, c2=c2, s1=s1, s2=s2,
        h1=login("s1@example.com"), h2=login("s2@example.com"),
        ha=login("admin@example.com"), hc=[login(u.email) for u in customers],
    )


def call_next(client, h, counter):
    return client.post(f"/api/staff/counters/{counter.id}/call-next", headers=h)


# ------------------------------------------------------------------ authorization
def test_staff_sees_only_their_counters(client, w):
    one = client.get("/api/staff/counters", headers=w.h1).get_json()["counters"]
    two = client.get("/api/staff/counters", headers=w.h2).get_json()["counters"]
    assert [c["name"] for c in one] == ["Counter 1"] and [c["name"] for c in two] == ["Counter 2"]
    assert one[0]["availability"] == "AVAILABLE" and one[0]["current_ticket"] is None


def test_only_staff_may_use_staff_endpoints(client, w):
    for h in (w.ha, w.hc[0]):
        assert client.get("/api/staff/counters", headers=h).status_code == 403
        assert call_next(client, h, w.c1).status_code == 403
        assert post(client, h, "/api/staff/tickets/1/start").status_code == 403
    assert client.get("/api/staff/counters").status_code == 401


def test_staff_cannot_operate_unassigned_counter(client, w):
    for path in ("open", "close", "call-next"):
        assert post(client, w.h1, f"/api/staff/counters/{w.c2.id}/{path}").status_code == 404
    assert client.get(f"/api/staff/counters/{w.c2.id}/queue", headers=w.h1).status_code == 404
    assert post(client, w.h1, "/api/staff/counters/999/open").status_code == 404


# ------------------------------------------------------------------ open / close
def test_open_close_rules(client, w, make_counter):
    closed = make_counter("Closed", w.gen, "CLOSED", [w.s1])
    inactive = make_counter("Off", w.gen, "INACTIVE", [w.s1])
    noservice = make_counter("Nosvc", None, "CLOSED", [w.s1])
    assert post(client, w.h1, f"/api/staff/counters/{closed.id}/open").get_json()["counter"]["status"] == "OPEN"
    assert post(client, w.h1, f"/api/staff/counters/{closed.id}/open").status_code == 409
    assert post(client, w.h1, f"/api/staff/counters/{inactive.id}/open").get_json()["error"] == "counter_inactive"
    assert post(client, w.h1, f"/api/staff/counters/{noservice.id}/open").get_json()["error"] == "no_service"
    assert post(client, w.h1, f"/api/staff/counters/{closed.id}/close").get_json()["counter"]["status"] == "CLOSED"
    assert post(client, w.h1, f"/api/staff/counters/{closed.id}/close").status_code == 409
    assert call_next(client, w.h1, closed).get_json()["error"] == "counter_not_open"


def test_cannot_close_counter_while_customer_present(client, w):
    join(client, w.hc[0], w.gen.id)
    call_next(client, w.h1, w.c1)
    res = post(client, w.h1, f"/api/staff/counters/{w.c1.id}/close")
    assert res.status_code == 409 and res.get_json()["error"] == "counter_busy"


# ------------------------------------------------------------------ calling
def test_call_next_takes_first_in_line_and_updates_customer_view(client, w):
    t = [join(client, h, w.gen.id) for h in w.hc[:3]]
    res = call_next(client, w.h1, w.c1)
    assert res.status_code == 200
    called = res.get_json()["ticket"]
    assert called["id"] == t[0]["id"] and called["status"] == "CALLED"
    assert called["customer"]["name"] == "Customer 0" and called["counter"]["name"] == "Counter 1"
    assert called["called_time"] is not None
    row = db.session.get(QueueTicket, called["id"])
    assert row.counter_id == w.c1.id

    mine = client.get(f"/api/queue/tickets/{t[0]['id']}", headers=w.hc[0]).get_json()["ticket"]
    assert mine["status"] == "CALLED" and mine["counter"]["name"] == "Counter 1" and mine["position"] is None
    assert client.get(f"/api/queue/tickets/{t[2]['id']}", headers=w.hc[2]).get_json()["ticket"]["people_ahead"] == 1
    # customers never receive other customers' names
    assert "customer" not in mine

    second = call_next(client, w.h2, w.c2).get_json()["ticket"]
    assert second["id"] == t[1]["id"] and second["counter"]["name"] == "Counter 2"


def test_call_next_empty_queue_and_other_service_not_called(client, w):
    assert call_next(client, w.h1, w.c1).get_json()["error"] == "queue_empty"
    join(client, w.hc[0], w.pay.id)  # different service
    assert call_next(client, w.h1, w.c1).status_code == 404


def test_cancelled_ticket_is_never_called(client, w):
    a = join(client, w.hc[0], w.gen.id)
    b = join(client, w.hc[1], w.gen.id)
    client.post(f"/api/queue/tickets/{a['id']}/cancel", headers=w.hc[0])
    assert call_next(client, w.h1, w.c1).get_json()["ticket"]["id"] == b["id"]


def test_counter_cannot_serve_two_customers(client, w):
    for h in w.hc[:3]:
        join(client, h, w.gen.id)
    first = call_next(client, w.h1, w.c1).get_json()["ticket"]
    assert call_next(client, w.h1, w.c1).get_json()["error"] == "counter_busy"
    post(client, w.h1, f"/api/staff/tickets/{first['id']}/start")
    assert call_next(client, w.h1, w.c1).get_json()["error"] == "counter_busy"
    post(client, w.h1, f"/api/staff/tickets/{first['id']}/complete")
    assert call_next(client, w.h1, w.c1).status_code == 200


# ------------------------------------------------------------------ service lifecycle & timing
def test_full_lifecycle_records_actual_times_in_minutes(client, w, monkeypatch):
    t = join(client, w.hc[0], w.gen.id)
    QueueTicket.query.filter_by(id=t["id"]).update({"join_time": T0})
    db.session.commit()
    clock = {"t": T0 + timedelta(minutes=5)}
    monkeypatch.setattr(staff_service, "_now", lambda: clock["t"])

    call_next(client, w.h1, w.c1)
    clock["t"] = T0 + timedelta(minutes=12, seconds=30)
    started = post(client, w.h1, f"/api/staff/tickets/{t['id']}/start").get_json()["ticket"]
    assert started["status"] == "SERVING" and started["actual_waiting_time"] == 12.5

    clock["t"] = T0 + timedelta(minutes=19, seconds=45)
    done = post(client, w.h1, f"/api/staff/tickets/{t['id']}/complete").get_json()["ticket"]
    assert done["status"] == "COMPLETED" and done["service_duration"] == 7.25
    assert done["actual_waiting_time"] == 12.5 and done["service_end_time"] is not None

    hist = client.get("/api/queue/history", headers=w.hc[0]).get_json()["tickets"][0]
    assert hist["actual_waiting_time"] == 12.5 and hist["service_duration"] == 7.25
    cap = client.get("/api/services", headers=w.hc[1]).get_json()["services"]
    gen = next(s for s in cap if s["prefix"] == "GEN")
    assert gen["counters"] == {"open": 2, "busy": 0, "available": 2}  # counter freed after completion


@pytest.mark.parametrize("action,prep,expected", [
    ("start", [], 409),                      # WAITING cannot start
    ("complete", ["call"], 409),             # CALLED cannot complete
    ("absent", [], 409),                     # WAITING cannot be absent
    ("start", ["call", "start"], 409),       # SERVING cannot start again
    ("absent", ["call", "start"], 409),      # SERVING cannot be absent
    ("skip", ["call", "start"], 409),        # SERVING cannot be skipped
    ("complete", ["call", "start", "complete"], 409),
])
def test_invalid_transitions_rejected(client, w, action, prep, expected):
    t = join(client, w.hc[0], w.gen.id)
    for step in prep:
        if step == "call":
            call_next(client, w.h1, w.c1)
        else:
            assert post(client, w.h1, f"/api/staff/tickets/{t['id']}/{step}").status_code == 200
    res = post(client, w.h1, f"/api/staff/tickets/{t['id']}/{action}")
    assert res.status_code == expected and res.get_json()["error"] == "invalid_transition"


def test_skip_and_absent_free_the_counter(client, w):
    ts = [join(client, h, w.gen.id) for h in w.hc[:3]]
    call_next(client, w.h1, w.c1)
    assert post(client, w.h1, f"/api/staff/tickets/{ts[0]['id']}/skip").get_json()["ticket"]["status"] == "SKIPPED"
    assert call_next(client, w.h1, w.c1).get_json()["ticket"]["id"] == ts[1]["id"]
    assert post(client, w.h1, f"/api/staff/tickets/{ts[1]['id']}/absent").get_json()["ticket"]["status"] == "ABSENT"
    assert call_next(client, w.h1, w.c1).get_json()["ticket"]["id"] == ts[2]["id"]
    # a skipped customer must rejoin and gets a new number
    again = client.post("/api/queue/join", json={"service_id": w.gen.id}, headers=w.hc[0])
    assert again.status_code == 201


def test_staff_can_skip_waiting_ticket_only_for_their_service(client, w):
    gen_t = join(client, w.hc[0], w.gen.id)
    pay_t = join(client, w.hc[1], w.pay.id)
    assert post(client, w.h1, f"/api/staff/tickets/{gen_t['id']}/skip").status_code == 200
    assert post(client, w.h1, f"/api/staff/tickets/{pay_t['id']}/skip").status_code == 404  # s1 has no PAY counter
    assert db.session.get(QueueTicket, pay_t["id"]).status == "WAITING"


def test_staff_cannot_act_on_ticket_at_someone_elses_counter(client, w):
    t = join(client, w.hc[0], w.gen.id)
    call_next(client, w.h1, w.c1)
    for action in ("start", "complete", "skip", "absent"):
        assert post(client, w.h2, f"/api/staff/tickets/{t['id']}/{action}").status_code == 404
    assert post(client, w.h1, "/api/staff/tickets/9999/start").status_code == 404
    assert db.session.get(QueueTicket, t["id"]).status == "CALLED"


# ------------------------------------------------------------------ concurrency protection
def test_database_allows_only_one_held_ticket_per_counter(w):
    def tk(uid, seq, status):
        return QueueTicket(queue_number=f"GEN-{seq:03d}", user_id=uid, service_id=w.gen.id, counter_id=w.c1.id,
                           queue_date=T0.date(), sequence=seq, status=status)
    db.session.add(tk(w.s1.id, 1, "CALLED"))
    db.session.commit()
    db.session.add(tk(w.s2.id, 2, "SERVING"))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()
    db.session.add(tk(w.s2.id, 3, "COMPLETED"))  # finished tickets do not count
    db.session.commit()


def test_two_counters_never_call_the_same_ticket(client, w, monkeypatch):
    """Second caller is handed a stale candidate (already called); compare-and-set must reject it."""
    a = join(client, w.hc[0], w.gen.id)
    b = join(client, w.hc[1], w.gen.id)
    assert call_next(client, w.h1, w.c1).get_json()["ticket"]["id"] == a["id"]

    real, calls = staff_service._waiting_candidates, {"n": 0}

    def stale_first(service_id):
        calls["n"] += 1
        return [a["id"]] if calls["n"] == 1 else real(service_id)

    monkeypatch.setattr(staff_service, "_waiting_candidates", stale_first)
    got = call_next(client, w.h2, w.c2).get_json()["ticket"]
    assert got["id"] == b["id"]
    assert db.session.get(QueueTicket, a["id"]).counter_id == w.c1.id  # untouched


def test_database_index_stops_double_booking_even_if_app_check_is_bypassed(client, w, monkeypatch):
    for h in w.hc[:2]:
        join(client, h, w.gen.id)
    call_next(client, w.h1, w.c1)
    monkeypatch.setattr(staff_service, "current_ticket", lambda _cid: None)  # app-level check blinded
    res = call_next(client, w.h1, w.c1)
    assert res.status_code == 409 and res.get_json()["error"] == "counter_busy"
    assert QueueTicket.query.filter_by(counter_id=w.c1.id, status="CALLED").count() == 1


# ------------------------------------------------------------------ queue view, stats, capacity
def test_counter_queue_view_and_real_statistics(client, w, monkeypatch):
    ts = [join(client, h, w.gen.id) for h in w.hc[:3]]
    clock = {"t": datetime.now(timezone.utc)}
    monkeypatch.setattr(staff_service, "_now", lambda: clock["t"])

    for dur in (4, 8):  # serve two customers: 4 and 8 minutes
        t = call_next(client, w.h1, w.c1).get_json()["ticket"]
        post(client, w.h1, f"/api/staff/tickets/{t['id']}/start")
        clock["t"] += timedelta(minutes=dur)
        post(client, w.h1, f"/api/staff/tickets/{t['id']}/complete")
    # an old completion (not today) must not be counted
    db.session.add(QueueTicket(queue_number="GEN-900", user_id=w.s2.id, service_id=w.gen.id, counter_id=w.c1.id,
                               queue_date=T0.date(), sequence=900, status="COMPLETED", service_duration=60.0,
                               service_end_time=datetime.now(timezone.utc) - timedelta(days=3)))
    db.session.commit()

    res = client.get(f"/api/staff/counters/{w.c1.id}/queue", headers=w.h1).get_json()
    assert res["stats"] == {"served_today": 2, "avg_service_duration_today": 6.0, "waiting_for_service": 1}
    assert [t["queue_number"] for t in res["waiting"]] == [ts[2]["queue_number"]]
    assert res["waiting"][0]["customer"]["name"] == "Customer 2" and res["waiting"][0]["position"] == 1


def test_capacity_counts_open_busy_available(client, w, make_counter):
    make_counter("Closed one", w.gen, "CLOSED", [w.s1])
    join(client, w.hc[0], w.gen.id)
    call_next(client, w.h1, w.c1)
    gen = next(s for s in client.get("/api/services", headers=w.hc[1]).get_json()["services"] if s["prefix"] == "GEN")
    assert gen["counters"] == {"open": 2, "busy": 1, "available": 1}
    pay = next(s for s in client.get("/api/services", headers=w.hc[1]).get_json()["services"] if s["prefix"] == "PAY")
    assert pay["counters"] == {"open": 0, "busy": 0, "available": 0}
