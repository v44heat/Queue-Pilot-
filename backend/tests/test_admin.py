from datetime import date, datetime, timedelta, timezone
from itertools import count
from types import SimpleNamespace

import pytest

from app.extensions import db
from app.models.queue import QueueTicket
from app.models.service import Service
from app.services import congestion_service, prediction_service

NOW = lambda: datetime.now(timezone.utc)  # noqa: E731
_seq = count(1)


@pytest.fixture()
def a(client, make_user, make_service, make_counter, login):
    gen, pay = make_service(), make_service("Payments", "PAY", 6)
    staff = make_user("STAFF", "staff@example.com", name="Sam Staff")
    make_user("ADMIN", "admin@example.com", name="Root Admin")
    make_user("CUSTOMER", "plain@example.com", name="Plain Customer")
    c1 = make_counter("GEN 1", gen, "OPEN", [staff])
    c2 = make_counter("PAY 1", pay, "CLOSED", [staff])
    return SimpleNamespace(
        gen=gen, pay=pay, staff=staff, c1=c1, c2=c2, make_user=make_user,
        h=login("admin@example.com"), hs=login("staff@example.com"), hc=login("plain@example.com"),
    )


def ticket(a, service, status, name=None, counter=None, **kw):
    """Insert a ticket directly with a fresh customer (one active ticket per customer per service)."""
    n = next(_seq)
    user = a.make_user("CUSTOMER", f"t{n}@example.com", name=name or f"Cust {n}")
    t = QueueTicket(queue_number=f"{service.prefix}-{n:03d}", user_id=user.id, service_id=service.id, queue_date=date(2026, 3, 2),
                    sequence=n, status=status, counter_id=counter.id if counter else None, **kw)
    db.session.add(t)
    db.session.commit()
    return t


def get(client, h, url):
    return client.get(url, headers=h)


# ------------------------------------------------------------------ permissions
def test_admin_endpoints_are_admin_only(client, a):
    urls = [("get", "/api/admin/dashboard"), ("get", "/api/admin/queue"), ("get", "/api/admin/services"),
            ("post", "/api/admin/services"), ("patch", "/api/admin/services/1"),
            ("get", "/api/settings"), ("patch", "/api/settings")]
    for method, url in urls:
        for h in (a.hs, a.hc):
            assert getattr(client, method)(url, headers=h, **({"json": {}} if method != "get" else {})).status_code == 403, (method, url)
        assert getattr(client, method)(url).status_code == 401, (method, url)


# ------------------------------------------------------------------ dashboard
def test_empty_system_dashboard_has_zeros_and_no_averages(client, a):
    d = get(client, a.h, "/api/admin/dashboard").get_json()
    s = d["summary"]
    assert (s["served_today"], s["waiting"], s["called"], s["being_served"]) == (0, 0, 0, 0)
    assert s["avg_waiting_time"] is None and s["avg_service_duration"] is None  # nothing measured: not 0
    assert s["active_counters"] == 1 and s["total_counters"] == 2 and s["congestion"]["level"] == "LOW"


def test_dashboard_figures_come_from_the_database(client, a):
    now = NOW()
    old = now - timedelta(days=3)
    # two completed today (waits 10 and 20, durations 4 and 8)
    for wait, dur in ((10.0, 4.0), (20.0, 8.0)):
        ticket(a, a.gen, "COMPLETED", counter=None, actual_waiting_time=wait, service_duration=dur,
               service_start_time=now - timedelta(minutes=dur + 1), service_end_time=now - timedelta(minutes=1))
    # one completed three days ago must not count as "today"
    ticket(a, a.gen, "COMPLETED", actual_waiting_time=100.0, service_duration=50.0, service_start_time=old, service_end_time=old)
    ticket(a, a.gen, "SERVING", counter=a.c1, actual_waiting_time=30.0, service_start_time=now)  # started today, waited 30
    for _ in range(3):
        ticket(a, a.gen, "WAITING")
    ticket(a, a.pay, "CALLED", counter=a.c2)

    d = get(client, a.h, "/api/admin/dashboard").get_json()
    s = d["summary"]
    assert s["served_today"] == 2
    assert (s["waiting"], s["called"], s["being_served"]) == (3, 1, 1)
    assert s["avg_waiting_time"] == 20.0  # (10 + 20 + 30) / 3, the old ticket excluded
    assert s["avg_service_duration"] == 6.0  # (4 + 8) / 2
    assert (s["active_counters"], s["busy_counters"], s["total_counters"]) == (1, 1, 2)
    rows = {r["prefix"]: r for r in d["services"]}
    assert rows["GEN"]["waiting"] == 3 and rows["GEN"]["serving"] == 1 and rows["GEN"]["counters"] == {"open": 1, "busy": 1, "available": 0}
    assert rows["PAY"]["called"] == 1 and rows["PAY"]["waiting"] == 0
    assert {c["name"]: c["availability"] for c in d["counters"]} == {"GEN 1": "BUSY", "PAY 1": "UNAVAILABLE"}
    assert d["counters"][0]["staff"][0]["name"] == "Sam Staff"


def test_dashboard_updates_as_the_database_changes(client, a):
    before = get(client, a.h, "/api/admin/dashboard").get_json()["summary"]["waiting"]
    h = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"email": "plain@example.com", "password": "Passw0rd!x"}).get_json()["access_token"]}
    assert client.post("/api/queue/join", json={"service_id": a.gen.id}, headers=h).status_code == 201
    assert get(client, a.h, "/api/admin/dashboard").get_json()["summary"]["waiting"] == before + 1


@pytest.mark.parametrize("waiting,level", [(0, "LOW"), (4, "LOW"), (5, "MODERATE"), (10, "MODERATE"), (11, "HIGH"), (20, "HIGH"), (21, "CRITICAL"), (80, "CRITICAL")])
def test_congestion_boundaries_are_inclusive_lower_bounds(app, waiting, level):
    assert congestion_service.level_for(waiting) == level


def test_system_congestion_is_the_worst_service_and_follows_waiting_counts(client, a):
    for _ in range(11):
        ticket(a, a.gen, "WAITING")
    for _ in range(5):
        ticket(a, a.pay, "WAITING")
    d = get(client, a.h, "/api/admin/dashboard").get_json()
    levels = {r["prefix"]: r["congestion"] for r in d["services"]}
    assert levels == {"GEN": "HIGH", "PAY": "MODERATE"} and d["summary"]["congestion"]["level"] == "HIGH"
    assert d["summary"]["congestion"]["thresholds"] == {"moderate": 5, "high": 11, "critical": 21}


# ------------------------------------------------------------------ live queue monitor
def test_monitor_lists_active_tickets_with_positions_and_estimates(client, a):
    w = [ticket(a, a.gen, "WAITING", name=f"Waiter {i}") for i in range(3)]
    s = ticket(a, a.gen, "SERVING", name="Being Served", counter=a.c1)
    p = ticket(a, a.pay, "WAITING", name="Payer")
    ticket(a, a.gen, "COMPLETED", name="Done Already")
    res = get(client, a.h, "/api/admin/queue").get_json()
    assert res["total"] == 5  # completed ticket is not in the default (active) view
    rows = {r["id"]: r for r in res["tickets"]}
    assert [rows[t.id]["position"] for t in w] == [1, 2, 3] and [rows[t.id]["people_ahead"] for t in w] == [0, 1, 2]
    assert [rows[t.id]["estimated_wait"]["minutes"] for t in w] == [0.0, 10.0, 20.0]  # fallback: ahead / 1 open counter x 10 min
    assert rows[w[0].id]["estimated_wait"]["source"] == "fallback"
    assert rows[w[0].id]["customer"]["name"] == "Waiter 0" and rows[w[0].id]["customer"]["email"].endswith("@example.com")
    assert rows[s.id]["position"] is None and rows[s.id]["estimated_wait"] is None and rows[s.id]["counter"]["name"] == "GEN 1"
    assert rows[p.id]["estimated_wait"]["source"] == "unavailable" and rows[p.id]["estimated_wait"]["minutes"] is None  # PAY counter closed
    assert {"id", "queue_number", "service", "customer", "status", "position", "estimated_wait", "counter"} <= set(rows[s.id])


def test_monitor_estimates_equal_what_the_customer_sees(client, a, login):
    ts = [ticket(a, a.gen, "WAITING") for _ in range(3)]
    batch = prediction_service.estimates_for(ts)
    for t in ts:
        ahead, est = batch[t.id]
        assert ahead == prediction_service.people_ahead(t) and est == prediction_service.live_estimate(t)
    owner = login(db.session.get(type(ts[2].user), ts[2].user_id).email)
    seen = client.get(f"/api/queue/tickets/{ts[2].id}", headers=owner).get_json()["ticket"]["estimated_wait"]
    assert seen == get(client, a.h, "/api/admin/queue").get_json()["tickets"][2]["estimated_wait"]


def test_monitor_filters_search_and_scope(client, a):
    ticket(a, a.gen, "WAITING", name="Alice Wonder")
    ticket(a, a.gen, "WAITING", name="Bob Builder")
    ticket(a, a.pay, "CALLED", name="Carol Pay", counter=a.c2)
    ticket(a, a.gen, "CANCELLED", name="Dan Gone")
    q = lambda s: get(client, a.h, f"/api/admin/queue?{s}").get_json()  # noqa: E731
    assert q("status=CALLED")["total"] == 1 and q("status=called")["tickets"][0]["customer"]["name"] == "Carol Pay"
    assert q(f"service_id={a.gen.id}")["total"] == 2
    assert q("status=ALL")["total"] == 4 and q("status=CANCELLED")["total"] == 1
    assert [t["customer"]["name"] for t in q("search=alice")["tickets"]] == ["Alice Wonder"]
    assert q("search=PAY-")["total"] == 1  # queue number search, case-insensitive
    assert q("search=nobody")["total"] == 0


def test_monitor_sorting_and_pagination(client, a):
    for n in ("Mia", "Zed", "Abe", "Kim", "Lee"):
        ticket(a, a.gen, "WAITING", name=n)
    names = lambda s: [t["customer"]["name"] for t in get(client, a.h, f"/api/admin/queue?{s}").get_json()["tickets"]]  # noqa: E731
    assert names("sort=customer&order=asc") == ["Abe", "Kim", "Lee", "Mia", "Zed"]
    assert names("sort=customer&order=desc") == ["Zed", "Mia", "Lee", "Kim", "Abe"]
    page = get(client, a.h, "/api/admin/queue?sort=customer&per_page=2&page=3").get_json()
    assert page["total"] == 5 and page["pages"] == 3 and [t["customer"]["name"] for t in page["tickets"]] == ["Zed"]
    assert names("") == ["Mia", "Zed", "Abe", "Kim", "Lee"]  # natural queue order by default


def test_monitor_rejects_bad_parameters(client, a):
    for bad in ("status=NOPE", "sort=password", "order=sideways", "page=x", "per_page=x", "service_id=abc"):
        assert get(client, a.h, f"/api/admin/queue?{bad}").status_code == 400, bad


# ------------------------------------------------------------------ services management
def post(client, h, **body):
    return client.post("/api/admin/services", json=body, headers=h)


def test_create_and_list_services_with_real_stats(client, a):
    res = post(client, a.h, name="Visa Desk", prefix="vis", description="Visa questions", default_service_duration=20)
    assert res.status_code == 201
    s = res.get_json()["service"]
    assert s["prefix"] == "VIS" and s["status"] == "ACTIVE" and s["default_service_duration"] == 20 and s["waiting_count"] == 0
    ticket(a, a.gen, "WAITING")
    listing = {x["prefix"]: x for x in get(client, a.h, "/api/admin/services").get_json()["services"]}
    assert listing["GEN"]["waiting_count"] == 1 and listing["GEN"]["active_tickets"] == 1 and listing["GEN"]["total_tickets"] == 1
    assert listing["GEN"]["counters"] == 1 and listing["GEN"]["open_counters"] == 1
    assert listing["VIS"]["total_tickets"] == 0


def test_new_service_appears_for_customers_and_can_be_joined(client, a):
    post(client, a.h, name="Visa Desk", prefix="VIS")
    names = [s["name"] for s in get(client, a.hc, "/api/services").get_json()["services"]]
    assert "Visa Desk" in names
    sid = next(s["id"] for s in get(client, a.hc, "/api/services").get_json()["services"] if s["prefix"] == "VIS")
    t = client.post("/api/queue/join", json={"service_id": sid}, headers=a.hc).get_json()["ticket"]
    assert t["queue_number"] == "VIS-001"


def test_service_validation_and_duplicates(client, a):
    bad = post(client, a.h, name="x", prefix="a-b", default_service_duration=0, description="d" * 501)
    assert bad.status_code == 400 and {"name", "prefix", "default_service_duration", "description"} <= set(bad.get_json()["details"])
    for body in (dict(name="Ok Name", prefix="TOOLONG1"), dict(name="Ok Name", prefix="X"), dict(name="Ok Name", prefix="OK", default_service_duration=True),
                 dict(name="Ok Name", prefix="OK", default_service_duration=241), dict(name="Ok Name", prefix="OK", default_service_duration="9")):
        assert post(client, a.h, **body).status_code == 400, body
    assert post(client, a.h, name="General Enquiry", prefix="NEW").status_code == 409  # name taken
    assert post(client, a.h, name="Brand New", prefix="gen").status_code == 409  # prefix taken (case-insensitive)
    assert client.post("/api/admin/services", data="x", headers=a.h).status_code == 400


def test_update_service_fields_and_prefix_lock(client, a):
    patch = lambda sid, **b: client.patch(f"/api/admin/services/{sid}", json=b, headers=a.h)  # noqa: E731
    ok = patch(a.pay.id, name="Fee Payments", description="Pay here", default_service_duration=8)
    assert ok.status_code == 200 and ok.get_json()["service"]["name"] == "Fee Payments" and ok.get_json()["service"]["default_service_duration"] == 8
    assert patch(a.pay.id, prefix="FEE").status_code == 200  # no tickets yet: allowed
    ticket(a, a.pay, "COMPLETED")
    locked = patch(a.pay.id, prefix="NEW")
    assert locked.status_code == 409 and locked.get_json()["error"] == "prefix_locked"
    assert patch(a.pay.id, prefix="FEE").status_code == 200  # unchanged value is not a change
    assert patch(a.pay.id, name="General Enquiry").status_code == 409
    assert patch(9999, name="Nope Nope").status_code == 404
    assert patch(a.pay.id).status_code == 400 and patch(a.pay.id, status="DELETED").status_code == 400


@pytest.mark.parametrize("active", ["WAITING", "CALLED", "SERVING"])
def test_cannot_deactivate_a_service_with_customers_in_the_queue(client, a, active):
    ticket(a, a.gen, active, counter=a.c1 if active != "WAITING" else None)
    res = client.patch(f"/api/admin/services/{a.gen.id}", json={"status": "INACTIVE"}, headers=a.h)
    assert res.status_code == 409 and res.get_json()["error"] == "service_in_use" and "1 customer is" in res.get_json()["message"]
    assert db.session.get(Service, a.gen.id).status == "ACTIVE"


def test_deactivating_hides_the_service_blocks_joining_and_counter_opening(client, a):
    ticket(a, a.pay, "COMPLETED")  # finished tickets do not block deactivation
    assert client.patch(f"/api/admin/services/{a.pay.id}", json={"status": "INACTIVE"}, headers=a.h).status_code == 200
    assert "Payments" not in [s["name"] for s in get(client, a.hc, "/api/services").get_json()["services"]]
    assert client.post("/api/queue/join", json={"service_id": a.pay.id}, headers=a.hc).status_code == 409
    res = client.post(f"/api/staff/counters/{a.c2.id}/open", headers=a.hs)
    assert res.status_code == 409 and res.get_json()["error"] == "service_inactive"
    assert "Payments" in [s["name"] for s in get(client, a.h, "/api/admin/services").get_json()["services"]]  # admin still sees it
    assert client.patch(f"/api/admin/services/{a.pay.id}", json={"status": "ACTIVE"}, headers=a.h).status_code == 200
    assert client.post(f"/api/staff/counters/{a.c2.id}/open", headers=a.hs).status_code == 200


# ------------------------------------------------------------------ users list sorting
def test_users_list_sorting(client, a):
    names = lambda s: [u["name"] for u in get(client, a.h, f"/api/users?{s}").get_json()["users"]]  # noqa: E731
    assert names("sort=name&order=asc") == ["Plain Customer", "Root Admin", "Sam Staff"]
    assert names("sort=name&order=desc") == ["Sam Staff", "Root Admin", "Plain Customer"]
    assert names("sort=role&order=asc")[0] == "Root Admin"  # ADMIN < CUSTOMER < STAFF
    for bad in ("sort=password_hash", "order=up"):
        assert get(client, a.h, f"/api/users?{bad}").status_code == 400
