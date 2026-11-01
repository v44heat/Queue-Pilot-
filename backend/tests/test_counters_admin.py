import pytest

from app.models.counter import Counter, StaffCounterAssignment
from app.extensions import db
from app.services.seed import seed_counters, seed_services


@pytest.fixture()
def adm(client, make_user, make_service, login):
    svc = make_service()
    make_user("ADMIN", "admin@example.com")
    staff = make_user("STAFF", "staff@example.com")
    make_user("CUSTOMER", "cust@example.com")
    return type("A", (), dict(
        svc=svc, staff=staff, h=login("admin@example.com"),
        hs=login("staff@example.com"), hc=login("cust@example.com"),
    ))


def create(client, h, **body):
    return client.post("/api/counters", json=body, headers=h)


def test_only_admin_can_configure_counters(client, adm):
    for h in (adm.hs, adm.hc):
        assert client.get("/api/counters", headers=h).status_code == 403
        assert create(client, h, name="X Counter").status_code == 403
        assert client.patch("/api/counters/1", json={"name": "Nope"}, headers=h).status_code == 403
        assert client.post("/api/counters/1/staff", json={"staff_id": 1}, headers=h).status_code == 403
    assert client.get("/api/counters").status_code == 401


def test_create_list_update_counter(client, adm):
    res = create(client, adm.h, name="Desk A", service_id=adm.svc.id)
    assert res.status_code == 201
    c = res.get_json()["counter"]
    assert c["status"] == "CLOSED" and c["service"]["name"] == "General Enquiry" and c["staff"] == []
    assert create(client, adm.h, name="Desk A").status_code == 409
    assert client.get("/api/counters", headers=adm.h).get_json()["counters"][0]["name"] == "Desk A"

    upd = client.patch(f"/api/counters/{c['id']}", json={"name": "Desk B", "status": "INACTIVE"}, headers=adm.h)
    assert upd.get_json()["counter"]["name"] == "Desk B" and upd.get_json()["counter"]["status"] == "INACTIVE"
    back = client.patch(f"/api/counters/{c['id']}", json={"status": "CLOSED"}, headers=adm.h)
    assert back.get_json()["counter"]["status"] == "CLOSED"
    assert client.patch("/api/counters/999", json={"name": "Zed Zed"}, headers=adm.h).status_code == 404


def test_validation_and_admin_cannot_open_counters(client, adm):
    bad = create(client, adm.h, name="x", service_id=999, status="OPEN")
    assert bad.status_code == 400 and {"name", "service_id", "status"} <= set(bad.get_json()["details"])
    c = create(client, adm.h, name="Desk A", service_id=adm.svc.id).get_json()["counter"]
    assert client.patch(f"/api/counters/{c['id']}", json={"status": "OPEN"}, headers=adm.h).status_code == 400
    assert client.patch(f"/api/counters/{c['id']}", json={}, headers=adm.h).status_code == 400


def test_admin_cannot_change_a_busy_counter(client, adm, make_user, login, make_counter):
    counter = make_counter("Busy", adm.svc, "OPEN", [adm.staff])
    cust = make_user("CUSTOMER", "waiting@example.com")
    client.post("/api/queue/join", json={"service_id": adm.svc.id}, headers=login(cust.email))
    client.post(f"/api/staff/counters/{counter.id}/call-next", headers=adm.hs)
    for body in ({"status": "INACTIVE"}, {"service_id": None}):
        res = client.patch(f"/api/counters/{counter.id}", json=body, headers=adm.h)
        assert res.status_code == 409 and res.get_json()["error"] == "counter_busy"
    # the only staff member cannot be removed while a customer is being served
    assert client.delete(f"/api/counters/{counter.id}/staff/{adm.staff.id}", headers=adm.h).status_code == 409
    assert client.patch(f"/api/counters/{counter.id}", json={"name": "Renamed"}, headers=adm.h).status_code == 200


def test_assign_and_unassign_staff(client, adm, make_user):
    c = create(client, adm.h, name="Desk A", service_id=adm.svc.id).get_json()["counter"]
    ok = client.post(f"/api/counters/{c['id']}/staff", json={"staff_id": adm.staff.id}, headers=adm.h)
    assert ok.status_code == 201 and ok.get_json()["counter"]["staff"][0]["email"] == "staff@example.com"
    assert client.post(f"/api/counters/{c['id']}/staff", json={"staff_id": adm.staff.id}, headers=adm.h).status_code == 409
    cust = make_user("CUSTOMER", "another@example.com")
    off = make_user("STAFF", "off@example.com", status="INACTIVE")
    for bad in ({"staff_id": cust.id}, {"staff_id": off.id}, {"staff_id": 999}, {"staff_id": "1"}, {}):
        assert client.post(f"/api/counters/{c['id']}/staff", json=bad, headers=adm.h).status_code == 400
    assert client.post("/api/counters/999/staff", json={"staff_id": adm.staff.id}, headers=adm.h).status_code == 404
    # assignment takes effect immediately for the staff member
    assert len(client.get("/api/staff/counters", headers=adm.hs).get_json()["counters"]) == 1
    assert client.delete(f"/api/counters/{c['id']}/staff/{adm.staff.id}", headers=adm.h).status_code == 200
    assert client.get("/api/staff/counters", headers=adm.hs).get_json()["counters"] == []
    assert client.delete(f"/api/counters/{c['id']}/staff/{adm.staff.id}", headers=adm.h).status_code == 404


# ------------------------------------------------------------------ seed / CLI
def test_seed_counters_idempotent(app):
    seed_services()
    assert seed_counters() == 5 and seed_counters() == 0
    assert {c.name for c in Counter.query.all()} >= {"GEN Counter 1", "PAY Counter 1"}
    assert all(c.status == "CLOSED" for c in Counter.query.all())


def test_assign_staff_cli(app, make_user, make_service, make_counter):
    make_user("STAFF", "cli@example.com")
    make_user("CUSTOMER", "notstaff@example.com")
    counter = make_counter("CLI Counter", make_service(), "CLOSED")
    runner = app.test_cli_runner()
    ok = runner.invoke(args=["assign-staff", "--email", "cli@example.com", "--counter-id", str(counter.id)])
    assert ok.exit_code == 0 and StaffCounterAssignment.query.count() == 1
    assert runner.invoke(args=["assign-staff", "--email", "cli@example.com", "--counter-id", str(counter.id)]).exit_code != 0
    assert runner.invoke(args=["assign-staff", "--email", "notstaff@example.com", "--counter-id", str(counter.id)]).exit_code != 0
    assert runner.invoke(args=["assign-staff", "--email", "cli@example.com", "--counter-id", "999"]).exit_code != 0
    assert "Created" in runner.invoke(args=["seed-counters"]).output
