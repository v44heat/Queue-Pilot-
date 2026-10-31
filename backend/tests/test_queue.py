from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.queue import TICKET_STATUSES, QueueCounter, QueueTicket
from app.services import queue_service
from app.services.queue_service import TRANSITIONS, QueueError, can_transition, transition
from app.services.seed import DEFAULT_SERVICES, seed_services


def join(client, headers, service_id):
    return client.post("/api/queue/join", json={"service_id": service_id}, headers=headers)


def set_status(ticket_id, status):
    QueueTicket.query.filter_by(id=ticket_id).update({"status": status})
    db.session.commit()


@pytest.fixture()
def setup(client, make_user, make_service, login):
    """Three logged-in customers and one active service."""
    svc = make_service()
    users = [make_user("CUSTOMER", f"c{i}@example.com", name=f"Customer {i}") for i in range(3)]
    heads = [login(u.email) for u in users]
    return svc, users, heads


# ---------------------------------------------------------------- state machine
def test_transition_table_matches_spec_exhaustively():
    valid = {
        ("WAITING", "CALLED"), ("CALLED", "SERVING"), ("SERVING", "COMPLETED"),
        ("WAITING", "CANCELLED"), ("WAITING", "SKIPPED"), ("CALLED", "ABSENT"), ("CALLED", "SKIPPED"),
    }
    for a in TICKET_STATUSES:
        for b in TICKET_STATUSES:
            assert can_transition(a, b) == ((a, b) in valid), (a, b)
    for terminal in ("COMPLETED", "CANCELLED", "SKIPPED", "ABSENT"):
        assert TRANSITIONS[terminal] == frozenset()


def test_transition_rejects_invalid_and_applies_valid(app):
    t = QueueTicket(status="WAITING")
    with pytest.raises(QueueError) as exc:
        transition(t, "SERVING")
    assert exc.value.code == "invalid_transition" and exc.value.status == 409
    assert t.status == "WAITING"
    transition(t, "CALLED")
    assert t.status == "CALLED"


# ---------------------------------------------------------------- services
def test_services_require_login_and_list_only_active(client, make_user, make_service, login):
    make_service()
    make_service(name="Payments", prefix="PAY", status="INACTIVE")
    assert client.get("/api/services").status_code == 401
    make_user("CUSTOMER", "c@example.com")
    res = client.get("/api/services", headers=login("c@example.com"))
    assert res.status_code == 200
    assert [s["name"] for s in res.get_json()["services"]] == ["General Enquiry"]


def test_service_waiting_count_is_live(client, setup):
    svc, _, heads = setup
    join(client, heads[0], svc.id)
    join(client, heads[1], svc.id)
    res = client.get(f"/api/services/{svc.id}", headers=heads[2]).get_json()
    assert res["service"]["waiting_count"] == 2
    assert client.get("/api/services/9999", headers=heads[2]).status_code == 404


# ---------------------------------------------------------------- joining
def test_join_creates_ticket_with_position(client, setup):
    svc, users, heads = setup
    res = join(client, heads[0], svc.id)
    assert res.status_code == 201
    t = res.get_json()["ticket"]
    assert t["queue_number"] == "GEN-001" and t["status"] == "WAITING"
    assert t["people_ahead"] == 0 and t["position"] == 1
    assert t["predicted_waiting_time"] is None  # prediction arrives in Phase 5; never fabricated
    assert t["service"]["name"] == "General Enquiry"
    row = db.session.get(QueueTicket, t["id"])
    assert row.user_id == users[0].id and row.join_time is not None

    t2 = join(client, heads[1], svc.id).get_json()["ticket"]
    assert t2["queue_number"] == "GEN-002" and t2["people_ahead"] == 1 and t2["position"] == 2


def test_numbering_is_per_service(client, setup, make_service):
    svc, _, heads = setup
    pay = make_service(name="Payments", prefix="PAY")
    assert join(client, heads[0], svc.id).get_json()["ticket"]["queue_number"] == "GEN-001"
    assert join(client, heads[0], pay.id).get_json()["ticket"]["queue_number"] == "PAY-001"
    # people ahead is also per service
    assert join(client, heads[1], pay.id).get_json()["ticket"]["people_ahead"] == 1


def test_duplicate_active_ticket_rejected_but_other_service_allowed(client, setup, make_service):
    svc, _, heads = setup
    assert join(client, heads[0], svc.id).status_code == 201
    dup = join(client, heads[0], svc.id)
    assert dup.status_code == 409 and dup.get_json()["error"] == "already_in_queue"
    other = make_service(name="Payments", prefix="PAY")
    assert join(client, heads[0], other.id).status_code == 201


@pytest.mark.parametrize("active_status", ["CALLED", "SERVING"])
def test_called_or_serving_ticket_still_blocks_rejoin(client, setup, active_status):
    svc, _, heads = setup
    tid = join(client, heads[0], svc.id).get_json()["ticket"]["id"]
    set_status(tid, active_status)
    assert join(client, heads[0], svc.id).status_code == 409


@pytest.mark.parametrize("terminal", ["COMPLETED", "CANCELLED", "SKIPPED", "ABSENT"])
def test_can_rejoin_after_terminal_status_with_new_number(client, setup, terminal):
    svc, _, heads = setup
    tid = join(client, heads[0], svc.id).get_json()["ticket"]["id"]
    set_status(tid, terminal)
    again = join(client, heads[0], svc.id)
    assert again.status_code == 201 and again.get_json()["ticket"]["queue_number"] == "GEN-002"


def test_join_validation_and_permissions(client, setup, make_service, make_user, login):
    svc, _, heads = setup
    inactive = make_service(name="Old", prefix="OLD", status="INACTIVE")
    assert join(client, heads[0], 9999).status_code == 404
    unavailable = join(client, heads[0], inactive.id)
    assert unavailable.status_code == 409 and unavailable.get_json()["error"] == "service_unavailable"
    for bad in ("1", None, True, 1.5, [1]):
        assert join(client, heads[0], bad).status_code == 400, bad
    assert client.post("/api/queue/join", data="nope", headers=heads[0]).status_code == 400
    assert client.post("/api/queue/join", json={"service_id": svc.id}).status_code == 401
    for role in ("STAFF", "ADMIN"):
        make_user(role, f"{role.lower()}@example.com")
        assert join(client, login(f"{role.lower()}@example.com"), svc.id).status_code == 403


def test_many_sequential_joins_get_unique_gap_free_numbers(client, make_user, make_service, login):
    svc = make_service()
    numbers = []
    for i in range(25):
        u = make_user("CUSTOMER", f"bulk{i}@example.com")
        numbers.append(join(client, login(u.email), svc.id).get_json()["ticket"]["queue_number"])
    assert numbers == [f"GEN-{n:03d}" for n in range(1, 26)]


# ---------------------------------------------------------------- numbering scope
def test_numbers_reset_daily_by_default(client, setup, monkeypatch):
    svc, _, heads = setup
    day = {"d": date(2026, 1, 1)}
    monkeypatch.setattr(queue_service, "_local_today", lambda: day["d"])
    assert join(client, heads[0], svc.id).get_json()["ticket"]["queue_number"] == "GEN-001"
    assert join(client, heads[1], svc.id).get_json()["ticket"]["queue_number"] == "GEN-002"
    day["d"] = date(2026, 1, 2)
    assert join(client, heads[2], svc.id).get_json()["ticket"]["queue_number"] == "GEN-001"


def test_numbers_continue_when_daily_reset_disabled(app, client, setup, monkeypatch):
    svc, _, heads = setup
    app.config["QUEUE_RESET_DAILY"] = False
    day = {"d": date(2026, 1, 1)}
    monkeypatch.setattr(queue_service, "_local_today", lambda: day["d"])
    join(client, heads[0], svc.id)
    day["d"] = date(2026, 1, 2)
    assert join(client, heads[1], svc.id).get_json()["ticket"]["queue_number"] == "GEN-002"


# ---------------------------------------------------------------- positions
def test_positions_recalculate_as_tickets_leave_the_line(client, setup):
    svc, _, heads = setup
    a = join(client, heads[0], svc.id).get_json()["ticket"]
    b = join(client, heads[1], svc.id).get_json()["ticket"]
    c = join(client, heads[2], svc.id).get_json()["ticket"]
    get = lambda h, t: client.get(f"/api/queue/tickets/{t['id']}", headers=h).get_json()["ticket"]
    assert (get(heads[2], c)["people_ahead"], get(heads[2], c)["position"]) == (2, 3)

    assert client.post(f"/api/queue/tickets/{a['id']}/cancel", headers=heads[0]).status_code == 200
    assert get(heads[1], b)["people_ahead"] == 0
    assert get(heads[2], c)["people_ahead"] == 1


@pytest.mark.parametrize("status", ["CALLED", "SERVING", "COMPLETED", "SKIPPED", "ABSENT", "CANCELLED"])
def test_only_waiting_tickets_count_as_ahead(client, setup, status):
    svc, _, heads = setup
    a = join(client, heads[0], svc.id).get_json()["ticket"]
    b = join(client, heads[1], svc.id).get_json()["ticket"]
    set_status(a["id"], status)
    got = client.get(f"/api/queue/tickets/{b['id']}", headers=heads[1]).get_json()["ticket"]
    assert got["people_ahead"] == 0 and got["position"] == 1
    gone = client.get(f"/api/queue/tickets/{a['id']}", headers=heads[0]).get_json()["ticket"]
    assert gone["position"] is None and gone["people_ahead"] is None  # no position once out of the line


# ---------------------------------------------------------------- cancellation
def test_cancel_own_waiting_ticket(client, setup):
    svc, _, heads = setup
    t = join(client, heads[0], svc.id).get_json()["ticket"]
    res = client.post(f"/api/queue/tickets/{t['id']}/cancel", headers=heads[0])
    assert res.status_code == 200 and res.get_json()["ticket"]["status"] == "CANCELLED"
    again = client.post(f"/api/queue/tickets/{t['id']}/cancel", headers=heads[0])
    assert again.status_code == 409
    rejoin = join(client, heads[0], svc.id)
    assert rejoin.status_code == 201 and rejoin.get_json()["ticket"]["queue_number"] == "GEN-002"


@pytest.mark.parametrize("status", ["CALLED", "SERVING", "COMPLETED", "SKIPPED", "ABSENT"])
def test_cannot_cancel_after_leaving_waiting(client, setup, status):
    svc, _, heads = setup
    t = join(client, heads[0], svc.id).get_json()["ticket"]
    set_status(t["id"], status)
    res = client.post(f"/api/queue/tickets/{t['id']}/cancel", headers=heads[0])
    assert res.status_code == 409 and res.get_json()["error"] == "cannot_cancel"
    assert db.session.get(QueueTicket, t["id"]).status == status


def test_cannot_cancel_someone_elses_ticket(client, setup):
    svc, _, heads = setup
    t = join(client, heads[0], svc.id).get_json()["ticket"]
    assert client.post(f"/api/queue/tickets/{t['id']}/cancel", headers=heads[1]).status_code == 404
    assert client.post("/api/queue/tickets/9999/cancel", headers=heads[1]).status_code == 404
    assert db.session.get(QueueTicket, t["id"]).status == "WAITING"


# ---------------------------------------------------------------- viewing
def test_ticket_visibility(client, setup, make_user, login):
    svc, _, heads = setup
    t = join(client, heads[0], svc.id).get_json()["ticket"]
    url = f"/api/queue/tickets/{t['id']}"
    assert client.get(url, headers=heads[0]).status_code == 200
    assert client.get(url, headers=heads[1]).status_code == 404  # other customer
    make_user("STAFF", "staff@example.com")
    assert client.get(url, headers=login("staff@example.com")).status_code == 200
    assert client.get(url).status_code == 401
    assert client.get("/api/queue/tickets/9999", headers=heads[0]).status_code == 404


def test_my_active_excludes_finished_tickets(client, setup, make_service):
    svc, _, heads = setup
    pay = make_service(name="Payments", prefix="PAY")
    a = join(client, heads[0], svc.id).get_json()["ticket"]
    join(client, heads[0], pay.id)
    client.post(f"/api/queue/tickets/{a['id']}/cancel", headers=heads[0])
    res = client.get("/api/queue/my-active", headers=heads[0]).get_json()["tickets"]
    assert [t["queue_number"] for t in res] == ["PAY-001"]


def test_history_paginates_filters_and_is_private(client, setup):
    svc, _, heads = setup
    for _ in range(3):
        t = join(client, heads[0], svc.id).get_json()["ticket"]
        client.post(f"/api/queue/tickets/{t['id']}/cancel", headers=heads[0])
    join(client, heads[0], svc.id)  # 4th, still waiting
    join(client, heads[1], svc.id)  # belongs to someone else

    page1 = client.get("/api/queue/history?per_page=3", headers=heads[0]).get_json()
    assert page1["total"] == 4 and page1["pages"] == 2 and len(page1["tickets"]) == 3
    assert page1["tickets"][0]["status"] == "WAITING"  # newest first
    cancelled = client.get("/api/queue/history?status=cancelled", headers=heads[0]).get_json()
    assert cancelled["total"] == 3
    assert client.get("/api/queue/history?status=NOPE", headers=heads[0]).status_code == 400
    assert client.get("/api/queue/history?page=x", headers=heads[0]).status_code == 400
    assert client.get("/api/queue/history").status_code == 401


# ---------------------------------------------------------------- concurrency protection (deterministic)
def _ticket(user_id, service_id, seq, status="WAITING", day=date(2026, 1, 1)):
    return QueueTicket(queue_number=f"GEN-{seq:03d}", user_id=user_id, service_id=service_id,
                       queue_date=day, sequence=seq, status=status)


def test_database_rejects_two_active_tickets_for_same_user_and_service(setup):
    svc, users, _ = setup
    db.session.add(_ticket(users[0].id, svc.id, 1))
    db.session.commit()
    db.session.add(_ticket(users[0].id, svc.id, 2))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()
    # finished tickets do not conflict with a new active one
    db.session.add(_ticket(users[1].id, svc.id, 3, status="CANCELLED"))
    db.session.add(_ticket(users[1].id, svc.id, 4))
    db.session.commit()


def test_database_rejects_duplicate_sequence_numbers(setup):
    svc, users, _ = setup
    db.session.add(_ticket(users[0].id, svc.id, 1))
    db.session.commit()
    db.session.add(_ticket(users[1].id, svc.id, 1))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_race_past_application_check_is_caught_by_database(client, setup, monkeypatch):
    """Simulates two requests that both pass the pre-check: the DB index must stop the second."""
    svc, _, heads = setup
    assert join(client, heads[0], svc.id).status_code == 201

    real = queue_service.active_ticket
    calls = {"n": 0}

    def blind_first_call(user_id, service_id):
        calls["n"] += 1
        return None if calls["n"] == 1 else real(user_id, service_id)

    monkeypatch.setattr(queue_service, "active_ticket", blind_first_call)
    res = join(client, heads[0], svc.id)
    assert res.status_code == 409 and res.get_json()["error"] == "already_in_queue"
    monkeypatch.setattr(queue_service, "active_ticket", real)
    # the failed attempt consumed no number: the next customer gets GEN-002, not GEN-003
    assert join(client, heads[1], svc.id).get_json()["ticket"]["queue_number"] == "GEN-002"
    assert QueueTicket.query.count() == 2


def test_counter_creation_race_is_retried(client, setup, monkeypatch):
    svc, _, heads = setup
    real_flush = db.session.flush
    state = {"n": 0}

    def flaky_flush(*a, **k):
        state["n"] += 1
        if state["n"] == 1:
            raise IntegrityError("INSERT counter", {}, Exception("duplicate counter"))
        return real_flush(*a, **k)

    monkeypatch.setattr(db.session, "flush", flaky_flush)
    res = join(client, heads[0], svc.id)
    assert res.status_code == 201 and res.get_json()["ticket"]["queue_number"] == "GEN-001"
    assert QueueCounter.query.count() == 1


# ---------------------------------------------------------------- seed
def test_seed_services_is_idempotent(app):
    assert seed_services() == len(DEFAULT_SERVICES) == 5
    assert seed_services() == 0
    from app.models.service import Service
    names = {s.name for s in Service.query.all()}
    assert {"General Enquiry", "Payments", "Registration", "Technical Support", "Document Collection"} == names
    assert {s.prefix for s in Service.query.all()} == {"GEN", "PAY", "REG", "TEC", "DOC"}


def test_seed_cli(app):
    runner = app.test_cli_runner()
    assert "Created 5" in runner.invoke(args=["seed-services"]).output
    assert "Created 0" in runner.invoke(args=["seed-services"]).output
