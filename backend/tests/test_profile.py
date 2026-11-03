from .conftest import PASSWORD


def test_update_own_name_and_phone_only(client, make_user, login):
    user = make_user("CUSTOMER", "me@example.com", name="Old Name")
    h = login("me@example.com")
    res = client.patch("/api/auth/me", json={"name": "New Name", "phone": "+254711111111",
                                             "role": "ADMIN", "status": "INACTIVE", "email": "evil@example.com"}, headers=h)
    assert res.status_code == 200
    body = res.get_json()["user"]
    assert body["name"] == "New Name" and body["phone"] == "+254711111111"
    assert body["role"] == "CUSTOMER" and body["status"] == "ACTIVE" and body["email"] == "me@example.com"
    assert client.get("/api/auth/me", headers=h).get_json()["user"]["name"] == "New Name"
    assert user.id == body["id"]


def test_profile_update_validation(client, make_user, login):
    make_user("CUSTOMER", "me@example.com")
    h = login("me@example.com")
    bad = client.patch("/api/auth/me", json={"name": "x", "phone": "abc"}, headers=h)
    assert bad.status_code == 400 and {"name", "phone"} <= set(bad.get_json()["details"])
    assert client.patch("/api/auth/me", json={}, headers=h).status_code == 400
    assert client.patch("/api/auth/me", json={"role": "ADMIN"}, headers=h).status_code == 400  # nothing editable supplied
    assert client.patch("/api/auth/me", json={"name": "Valid Name"}).status_code == 401
    cleared = client.patch("/api/auth/me", json={"phone": ""}, headers=h)
    assert cleared.status_code == 200 and cleared.get_json()["user"]["phone"] is None


def test_change_password_flow(client, make_user, login):
    make_user("CUSTOMER", "me@example.com")
    h = login("me@example.com")
    new = "Brand-new1pw"
    assert client.post("/api/auth/change-password", json={"current_password": PASSWORD, "new_password": new}, headers=h).status_code == 200
    assert client.post("/api/auth/login", json={"email": "me@example.com", "password": PASSWORD}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "me@example.com", "password": new}).status_code == 200


def test_change_password_rejections(client, make_user, login):
    make_user("CUSTOMER", "me@example.com")
    h = login("me@example.com")
    url = "/api/auth/change-password"
    wrong = client.post(url, json={"current_password": "Wrong1234", "new_password": "Another1pass"}, headers=h)
    assert wrong.status_code == 400 and wrong.get_json()["error"] == "incorrect_password"  # 400, not 401
    assert client.post(url, json={"current_password": PASSWORD, "new_password": "short"}, headers=h).status_code == 400
    assert client.post(url, json={"current_password": PASSWORD, "new_password": "nodigitshere"}, headers=h).status_code == 400
    assert client.post(url, json={"current_password": PASSWORD, "new_password": PASSWORD}, headers=h).status_code == 400
    assert client.post(url, json={"new_password": "Another1pass"}, headers=h).status_code == 400
    assert client.post(url, json={"current_password": PASSWORD, "new_password": "Another1pass"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "me@example.com", "password": PASSWORD}).status_code == 200  # unchanged
