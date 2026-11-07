from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.counter import CounterSession
from app.models.queue import QueueTicket


@pytest.fixture()
def w(client, make_user, make_service, make_counter, login):
    gen = make_service()
    staff = make_user("STAFF", "staff@example.com")
    make_user("ADMIN", "admin@example.com")
    counter = make_counter("C1", gen, "CLOSED", [staff])
    custs = [make_user("CUSTOMER", f"c{i}@example.com") for i in range(3)]
    return SimpleNamespace(gen=gen, staff=staff, counter=counter, hs=login("staff@example.com"), ha=login("admin@example.com"),
                           hc=[login(u.email) for u in custs])


def join(client, h, sid):
    return client.post("/api/queue/join", json={"service_id": sid}, headers=h).get_json()["ticket"]


def ticket(tid):
    return db.session.get(QueueTicket, tid)


# ------------------------------------------------------------------ when a ticket leaves the waiting line
def test_waiting_ticket_has_no_end_time_yet(client, w):
    t = join(client, w.hc[0], w.gen.id)
    assert ticket(t["id"]).wait_ended_time is None


def test_cancelling_records_when_the_ticket_left_the_line(client, w):
    t = join(client, w.hc[0], w.gen.id)
    client.post(f"/api/queue/tickets/{t['id']}/cancel", headers=w.hc[0])
    row = ticket(t["id"])
    assert row.wait_ended_time is not None and row.wait_ended_time >= row.join_time.replace(tzinfo=row.wait_ended_time.tzinfo)


def test_calling_records_the_same_moment_as_called_time(client, w):
    client.post(f"/api/staff/counters/{w.counter.id}/open", headers=w.hs)
    t = join(client, w.hc[0], w.gen.id)
    client.post(f"/api/staff/counters/{w.counter.id}/call-next", headers=w.hs)
    row = ticket(t["id"])
    assert row.wait_ended_time == row.called_time


def test_skipping_a_waiting_ticket_records_it_but_later_steps_do_not_overwrite(client, w):
    client.post(f"/api/staff/counters/{w.counter.id}/open", headers=w.hs)
    a, b = join(client, w.hc[0], w.gen.id), join(client, w.hc[1], w.gen.id)
    client.post(f"/api/staff/tickets/{b['id']}/skip", headers=w.hs)
    assert ticket(b["id"]).wait_ended_time is not None
    client.post(f"/api/staff/counters/{w.counter.id}/call-next", headers=w.hs)
    left = ticket(a["id"]).wait_ended_time
    client.post(f"/api/staff/tickets/{a['id']}/start", headers=w.hs)
    client.post(f"/api/staff/tickets/{a['id']}/complete", headers=w.hs)
    assert ticket(a["id"]).wait_ended_time == left  # leaving WAITING is recorded once


# ------------------------------------------------------------------ counter open sessions
def sessions():
    return CounterSession.query.order_by(CounterSession.id).all()


def test_opening_and_closing_a_counter_records_sessions(client, w):
    assert sessions() == []
    client.post(f"/api/staff/counters/{w.counter.id}/open", headers=w.hs)
    [s] = sessions()
    assert s.closed_at is None and s.opened_by == w.staff.id and s.counter_id == w.counter.id
    client.post(f"/api/staff/counters/{w.counter.id}/close", headers=w.hs)
    assert sessions()[0].closed_at is not None
    client.post(f"/api/staff/counters/{w.counter.id}/open", headers=w.hs)
    assert len(sessions()) == 2 and sessions()[1].closed_at is None  # a fresh session for the second shift


def test_failed_open_or_close_creates_no_session(client, w):
    client.post(f"/api/staff/counters/{w.counter.id}/close", headers=w.hs)  # not open: refused
    assert sessions() == []
    client.post(f"/api/staff/counters/{w.counter.id}/open", headers=w.hs)
    client.post(f"/api/staff/counters/{w.counter.id}/open", headers=w.hs)  # already open: refused
    assert len(sessions()) == 1


@pytest.mark.parametrize("new_status", ["CLOSED", "INACTIVE"])
def test_admin_taking_an_open_counter_out_of_service_closes_its_session(client, w, new_status):
    client.post(f"/api/staff/counters/{w.counter.id}/open", headers=w.hs)
    res = client.patch(f"/api/counters/{w.counter.id}", json={"status": new_status}, headers=w.ha)
    assert res.status_code == 200 and sessions()[0].closed_at is not None


def test_admin_rename_does_not_touch_the_open_session(client, w):
    client.post(f"/api/staff/counters/{w.counter.id}/open", headers=w.hs)
    client.patch(f"/api/counters/{w.counter.id}", json={"name": "Renamed"}, headers=w.ha)
    assert sessions()[0].closed_at is None


def test_database_allows_only_one_open_session_per_counter(client, w):
    client.post(f"/api/staff/counters/{w.counter.id}/open", headers=w.hs)
    db.session.add(CounterSession(counter_id=w.counter.id))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()
