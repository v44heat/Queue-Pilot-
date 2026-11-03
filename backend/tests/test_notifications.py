from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.notification import Notification
from app.models.queue import QueueTicket
from app.services import notification_service
from app.services.notification_service import is_significant_change


@pytest.fixture()
def w(client, make_user, make_service, make_counter, login):
    gen = make_service()
    staff = make_user("STAFF", "staff@example.com")
    counter = make_counter("Counter 1", gen, "OPEN", [staff])
    custs = [make_user("CUSTOMER", f"c{i}@example.com", name=f"Customer {i}") for i in range(5)]
    return SimpleNamespace(gen=gen, counter=counter, custs=custs, hs=login("staff@example.com"),
                           hc=[login(u.email) for u in custs])


def join(client, h, sid):
    res = client.post("/api/queue/join", json={"service_id": sid}, headers=h)
    assert res.status_code == 201, res.get_json()
    return res.get_json()["ticket"]


def notes(client, h, type_=None):
    items = client.get("/api/notifications?per_page=50", headers=h).get_json()["notifications"]
    return [n for n in items if type_ is None or n["type"] == type_]


def call_next(client, w):
    res = client.post(f"/api/staff/counters/{w.counter.id}/call-next", headers=w.hs)
    assert res.status_code == 200, res.get_json()
    return res.get_json()["ticket"]


def finish(client, w, ticket):
    client.post(f"/api/staff/tickets/{ticket['id']}/start", headers=w.hs)
    client.post(f"/api/staff/tickets/{ticket['id']}/complete", headers=w.hs)


# ------------------------------------------------------------------ threshold rule
@pytest.mark.parametrize("old,new,expected", [
    (30, 10, True), (30, 25, False), (10, 19, False), (10, 20, True), (0, 12, True), (0, 9, False),
    (100, 108, False), (100, 110, False), (40, 30, True), (5, 5, False),
])
def test_significant_change_rule(old, new, expected):
    assert is_significant_change(old, new) is expected


# ------------------------------------------------------------------ joined
def test_joining_creates_a_persistent_notification_with_real_values(client, w):
    join(client, w.hc[0], w.gen.id)
    t = join(client, w.hc[1], w.gen.id)
    n = notes(client, w.hc[1], "QUEUE_JOINED")
    assert len(n) == 1 and n[0]["is_read"] is False and n[0]["queue_ticket_id"] == t["id"]
    assert t["queue_number"] in n[0]["message"] and "1 person is ahead of you" in n[0]["message"]
    assert "Estimated wait: about 10 minutes" in n[0]["message"]
    assert Notification.query.filter_by(user_id=w.custs[1].id).count() == 1  # stored in the database


def test_joined_message_has_no_estimate_when_none_exists(client, w):
    w.counter.status = "CLOSED"
    db.session.commit()
    join(client, w.hc[0], w.gen.id)
    msg = notes(client, w.hc[0], "QUEUE_JOINED")[0]["message"]
    assert "Nobody is ahead of you." in msg and "Estimated" not in msg


# ------------------------------------------------------------------ called
def test_called_notification_names_the_counter_and_goes_only_to_that_customer(client, w):
    for h in w.hc[:3]:
        join(client, h, w.gen.id)
    call_next(client, w)
    called = notes(client, w.hc[0], "CALLED")
    assert len(called) == 1 and "Counter 1" in called[0]["message"]
    assert notes(client, w.hc[1], "CALLED") == [] and notes(client, w.hc[2], "CALLED") == []


# ------------------------------------------------------------------ approaching
def test_turn_approaching_is_sent_once_to_customers_near_the_front(client, w):
    tickets = [join(client, h, w.gen.id) for h in w.hc]  # 5 customers: ahead 0..4
    assert all(notes(client, h, "TURN_APPROACHING") == [] for h in w.hc)  # nothing yet: nobody has left the line
    first = call_next(client, w)  # remaining: c1 ahead0, c2 ahead1, c3 ahead2, c4 ahead3
    assert [len(notes(client, h, "TURN_APPROACHING")) for h in w.hc] == [0, 1, 1, 1, 0]
    assert "you're next" in notes(client, w.hc[1], "TURN_APPROACHING")[0]["message"]
    assert "2 people are ahead of you" in notes(client, w.hc[3], "TURN_APPROACHING")[0]["message"]
    finish(client, w, first)
    call_next(client, w)  # c1 called; c4 now has 2 ahead
    assert [len(notes(client, h, "TURN_APPROACHING")) for h in w.hc] == [0, 1, 1, 1, 1]  # still once each
    assert tickets[4]["queue_number"] in notes(client, w.hc[4], "TURN_APPROACHING")[0]["message"]


def test_customer_cancelling_moves_others_up_and_notifies_them(client, w):
    t = [join(client, h, w.gen.id) for h in w.hc[:5]]
    client.post(f"/api/queue/tickets/{t[0]['id']}/cancel", headers=w.hc[0])
    # c1,c2,c3 now have 0,1,2 ahead -> approaching; c4 has 3 ahead -> not yet
    assert [len(notes(client, h, "TURN_APPROACHING")) for h in w.hc] == [0, 1, 1, 1, 0]
    cancelled = notes(client, w.hc[0], "CANCELLED")
    assert len(cancelled) == 1 and t[0]["queue_number"] in cancelled[0]["message"]
    client.post(f"/api/queue/tickets/{t[0]['id']}/cancel", headers=w.hc[0])  # already cancelled: rejected
    assert len(notes(client, w.hc[0], "CANCELLED")) == 1


def test_skip_and_absent_notify_the_customer_with_next_steps(client, w):
    a, b = join(client, w.hc[0], w.gen.id), join(client, w.hc[1], w.gen.id)
    c = join(client, w.hc[2], w.gen.id)
    call_next(client, w)  # a called
    client.post(f"/api/staff/tickets/{a['id']}/absent", headers=w.hs)
    absent = notes(client, w.hc[0], "ABSENT")
    assert len(absent) == 1 and "Join the queue again" in absent[0]["message"]
    client.post(f"/api/staff/tickets/{b['id']}/skip", headers=w.hs)  # waiting ticket skipped
    skipped = notes(client, w.hc[1], "SKIPPED")
    assert len(skipped) == 1 and b["queue_number"] in skipped[0]["message"]
    assert len(notes(client, w.hc[2], "TURN_APPROACHING")) == 1  # c moved to the front


# ------------------------------------------------------------------ waiting time changed
def test_significant_estimate_change_notifies_once_then_resets_the_baseline(client, w):
    t = [join(client, h, w.gen.id) for h in w.hc[:4]]  # c3 predicted 30 minutes (3 ahead x 10 / 1 counter)
    assert t[3]["predicted_waiting_time"] == 30.0
    url = f"/api/queue/tickets/{t[3]['id']}"
    assert notes(client, w.hc[3], "WAIT_TIME_CHANGED") == []
    client.get(url, headers=w.hc[3])  # unchanged estimate: nothing
    assert notes(client, w.hc[3], "WAIT_TIME_CHANGED") == []
    client.post(f"/api/queue/tickets/{t[0]['id']}/cancel", headers=w.hc[0])
    client.post(f"/api/queue/tickets/{t[1]['id']}/cancel", headers=w.hc[1])  # now only 1 ahead -> 10 minutes
    got = client.get(url, headers=w.hc[3]).get_json()["ticket"]
    assert got["estimated_wait"]["minutes"] == 10.0
    changed = notes(client, w.hc[3], "WAIT_TIME_CHANGED")
    assert len(changed) == 1 and "from about 30 to about 10 minutes" in changed[0]["message"]
    client.get(url, headers=w.hc[3])  # same estimate again: no duplicate
    assert len(notes(client, w.hc[3], "WAIT_TIME_CHANGED")) == 1
    assert got["predicted_waiting_time"] == 30.0  # original prediction untouched for evaluation


def test_only_the_owner_refreshing_triggers_a_wait_change_notification(client, w):
    t = [join(client, h, w.gen.id) for h in w.hc[:4]]
    client.post(f"/api/queue/tickets/{t[0]['id']}/cancel", headers=w.hc[0])
    client.post(f"/api/queue/tickets/{t[1]['id']}/cancel", headers=w.hc[1])
    client.get(f"/api/queue/tickets/{t[3]['id']}", headers=w.hs)  # staff view must not write
    assert notes(client, w.hc[3], "WAIT_TIME_CHANGED") == []
    client.get("/api/queue/my-active", headers=w.hc[3])  # the owner's refresh does
    assert len(notes(client, w.hc[3], "WAIT_TIME_CHANGED")) == 1


def test_first_usable_estimate_is_recorded_silently(client, w):
    w.counter.status = "CLOSED"
    db.session.commit()
    t = join(client, w.hc[0], w.gen.id)  # no estimate at join
    w.counter.status = "OPEN"
    db.session.commit()
    client.get(f"/api/queue/tickets/{t['id']}", headers=w.hc[0])
    assert notes(client, w.hc[0], "WAIT_TIME_CHANGED") == []
    assert db.session.get(QueueTicket, t["id"]).notified_wait_estimate is not None  # baseline now stored


# ------------------------------------------------------------------ robustness
def test_notification_failure_never_blocks_queue_operations(client, w, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("storage down")
    monkeypatch.setattr(notification_service, "Notification", boom)
    t = join(client, w.hc[0], w.gen.id)  # 201 asserted inside join()
    join(client, w.hc[1], w.gen.id)
    res = client.post(f"/api/staff/counters/{w.counter.id}/call-next", headers=w.hs)
    assert res.status_code == 200 and res.get_json()["ticket"]["id"] == t["id"]
    assert client.post(f"/api/queue/tickets/{t['id']}/cancel", headers=w.hc[0]).status_code == 409  # called: normal rule
    assert Notification.query.count() == 0


def test_database_enforces_once_only_notifications(w):
    db.session.add(Notification(user_id=w.custs[0].id, type="CALLED", title="x", message="y", dedupe_key="1:CALLED"))
    db.session.commit()
    db.session.add(Notification(user_id=w.custs[0].id, type="CALLED", title="x", message="y", dedupe_key="1:CALLED"))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()
    for _ in range(2):  # repeatable notifications have no key and may repeat
        db.session.add(Notification(user_id=w.custs[0].id, type="WAIT_TIME_CHANGED", title="x", message="y"))
    db.session.commit()
    db.session.add(Notification(user_id=w.custs[0].id, type="BOGUS", title="x", message="y"))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


# ------------------------------------------------------------------ API
def test_notification_api_lists_counts_and_marks_read(client, w):
    for h in w.hc[:3]:
        join(client, h, w.gen.id)
    call_next(client, w)
    h = w.hc[0]
    listing = client.get("/api/notifications", headers=h).get_json()
    assert listing["total"] == 2 and listing["unread"] == 2  # joined + called, newest first
    assert [n["type"] for n in listing["notifications"]] == ["CALLED", "QUEUE_JOINED"]
    assert client.get("/api/notifications/unread-count", headers=h).get_json() == {"unread": 2}

    first = listing["notifications"][0]["id"]
    res = client.post(f"/api/notifications/{first}/read", headers=h)
    assert res.status_code == 200 and res.get_json()["notification"]["is_read"] is True
    assert client.get("/api/notifications/unread-count", headers=h).get_json()["unread"] == 1
    only_unread = client.get("/api/notifications?unread_only=true", headers=h).get_json()
    assert [n["type"] for n in only_unread["notifications"]] == ["QUEUE_JOINED"]
    assert client.post("/api/notifications/read-all", headers=h).get_json() == {"updated": 1}
    assert client.get("/api/notifications/unread-count", headers=h).get_json()["unread"] == 0


def test_notifications_are_private_and_need_login(client, w):
    join(client, w.hc[0], w.gen.id)
    nid = notes(client, w.hc[0])[0]["id"]
    assert client.post(f"/api/notifications/{nid}/read", headers=w.hc[1]).status_code == 404
    assert client.post("/api/notifications/9999/read", headers=w.hc[0]).status_code == 404
    assert client.get("/api/notifications", headers=w.hc[1]).get_json()["total"] == 0
    assert client.post("/api/notifications/read-all", headers=w.hc[1]).get_json() == {"updated": 0}
    assert Notification.query.get(nid).is_read is False  # untouched by the other customer
    for url in ("/api/notifications", "/api/notifications/unread-count"):
        assert client.get(url).status_code == 401
    assert client.post(f"/api/notifications/{nid}/read").status_code == 401


def test_notification_pagination(client, w):
    for _ in range(7):
        db.session.add(Notification(user_id=w.custs[0].id, type="WAIT_TIME_CHANGED", title="t", message="m"))
    db.session.commit()
    page = client.get("/api/notifications?per_page=3&page=3", headers=w.hc[0]).get_json()
    assert page["total"] == 7 and page["pages"] == 3 and len(page["notifications"]) == 1
    assert client.get("/api/notifications?page=x", headers=w.hc[0]).status_code == 400
