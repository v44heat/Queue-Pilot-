from app.models.user import User

from .conftest import PASSWORD


def test_customer_and_staff_cannot_use_admin_api(client, make_user, login):
    make_user("CUSTOMER", "cust@example.com")
    make_user("STAFF", "staff@example.com")
    for email in ("cust@example.com", "staff@example.com"):
        h = login(email)
        assert client.get("/api/users", headers=h).status_code == 403
        assert client.post("/api/users", json={}, headers=h).status_code == 403
        assert client.patch("/api/users/1", json={"role": "ADMIN"}, headers=h).status_code == 403


def test_admin_lists_searches_and_paginates(client, make_user, login):
    make_user("ADMIN", "admin@example.com")
    for i in range(12):
        make_user("CUSTOMER", f"person{i}@example.com", name=f"Person {i}")
    h = login("admin@example.com")
    res = client.get("/api/users?per_page=5&page=2", headers=h).get_json()
    assert res["total"] == 13 and res["pages"] == 3 and len(res["users"]) == 5
    found = client.get("/api/users?search=person11", headers=h).get_json()
    assert [u["email"] for u in found["users"]] == ["person11@example.com"]
    admins = client.get("/api/users?role=ADMIN", headers=h).get_json()
    assert admins["total"] == 1
    assert all("password_hash" not in u for u in res["users"])


def test_admin_creates_staff_account(client, make_user, login):
    make_user("ADMIN", "admin@example.com")
    h = login("admin@example.com")
    res = client.post("/api/users", headers=h, json={"name": "Sam Staff", "email": "sam@example.com", "password": PASSWORD, "role": "STAFF"})
    assert res.status_code == 201 and res.get_json()["user"]["role"] == "STAFF"
    bad = client.post("/api/users", headers=h, json={"name": "Z Z", "email": "z@example.com", "password": PASSWORD, "role": "SUPERUSER"})
    assert bad.status_code == 400


def test_role_change_enforced_immediately(client, make_user, login):
    admin = make_user("ADMIN", "admin@example.com")
    other = make_user("ADMIN", "other@example.com")
    other_headers = login("other@example.com")
    assert client.get("/api/users", headers=other_headers).status_code == 200
    h = login("admin@example.com")
    assert client.patch(f"/api/users/{other.id}", json={"role": "CUSTOMER"}, headers=h).status_code == 200
    # Same, still-valid token must now be rejected: role is read from the DB.
    assert client.get("/api/users", headers=other_headers).status_code == 403
    assert admin.id != other.id


def test_deactivated_user_token_rejected(client, make_user, login):
    make_user("ADMIN", "admin@example.com")
    cust = make_user("CUSTOMER", "cust@example.com")
    cust_headers = login("cust@example.com")
    h = login("admin@example.com")
    client.patch(f"/api/users/{cust.id}", json={"status": "INACTIVE"}, headers=h)
    res = client.get("/api/auth/me", headers=cust_headers)
    assert res.status_code == 403 and res.get_json()["error"] == "account_disabled"


def test_admin_cannot_change_own_role_or_status(client, make_user, login):
    admin = make_user("ADMIN", "admin@example.com")
    h = login("admin@example.com")
    assert client.patch(f"/api/users/{admin.id}", json={"role": "CUSTOMER"}, headers=h).status_code == 403
    assert client.patch(f"/api/users/{admin.id}", json={"status": "INACTIVE"}, headers=h).status_code == 403
    ok = client.patch(f"/api/users/{admin.id}", json={"name": "Renamed Admin"}, headers=h)
    assert ok.status_code == 200 and User.query.get(admin.id).role == "ADMIN"


def test_update_validation_and_not_found(client, make_user, login):
    make_user("ADMIN", "admin@example.com")
    h = login("admin@example.com")
    assert client.patch("/api/users/999", json={"name": "Nope Nope"}, headers=h).status_code == 404
    assert client.patch("/api/users/1", json={"role": "GOD"}, headers=h).status_code == 400
    assert client.patch("/api/users/1", json={}, headers=h).status_code == 400
