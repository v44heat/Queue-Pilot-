from app import create_app
from app.extensions import db
from app.models.user import TokenBlocklist, User

from .conftest import PASSWORD


def register(client, **over):
    payload = {"name": "Jane Doe", "email": "Jane@Example.com", "password": PASSWORD, "phone": "+254700000000"}
    payload.update(over)
    return client.post("/api/auth/register", json=payload)


def test_register_success_hashes_password(client):
    res = register(client)
    assert res.status_code == 201
    body = res.get_json()
    assert body["user"]["role"] == "CUSTOMER"
    assert body["user"]["email"] == "jane@example.com"  # normalised
    assert "password" not in body["user"] and "password_hash" not in body["user"]
    user = User.query.filter_by(email="jane@example.com").one()
    assert user.password_hash != PASSWORD and PASSWORD not in user.password_hash


def test_register_cannot_create_admin_or_staff(client):
    for role in ("ADMIN", "STAFF"):
        res = register(client, email=f"{role}@example.com", role=role)
        assert res.status_code == 201
        assert res.get_json()["user"]["role"] == "CUSTOMER"


def test_register_duplicate_email_conflict(client):
    assert register(client).status_code == 201
    res = register(client, email="jane@example.com")
    assert res.status_code == 409


def test_register_validation_errors(client):
    res = register(client, name="", email="bad", password="short", phone="abc")
    assert res.status_code == 400
    details = res.get_json()["details"]
    assert {"name", "email", "password", "phone"} <= set(details)


def test_login_success_and_me(client):
    register(client)
    res = client.post("/api/auth/login", json={"email": "JANE@example.com", "password": PASSWORD})
    assert res.status_code == 200
    token = res.get_json()["access_token"]
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200 and me.get_json()["user"]["email"] == "jane@example.com"


def test_login_invalid_credentials_generic_message(client):
    register(client)
    wrong_pw = client.post("/api/auth/login", json={"email": "jane@example.com", "password": "Wrong1234"})
    unknown = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "Wrong1234"})
    assert wrong_pw.status_code == unknown.status_code == 401
    assert wrong_pw.get_json()["message"] == unknown.get_json()["message"]


def test_login_missing_fields(client):
    assert client.post("/api/auth/login", json={}).status_code == 400


def test_inactive_user_cannot_login(client, make_user):
    make_user(email="off@example.com", status="INACTIVE")
    res = client.post("/api/auth/login", json={"email": "off@example.com", "password": PASSWORD})
    assert res.status_code == 403 and res.get_json()["error"] == "account_disabled"


def test_protected_endpoints_reject_anonymous_and_garbage_tokens(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/users").status_code == 401
    res = client.get("/api/auth/me", headers={"Authorization": "Bearer not.a.jwt"})
    assert res.status_code == 401 and res.get_json()["error"] == "invalid_token"


def test_logout_revokes_token(client, make_user, login):
    make_user(email="c@example.com")
    headers = login("c@example.com")
    assert client.post("/api/auth/logout", headers=headers).status_code == 200
    assert TokenBlocklist.query.count() == 1
    res = client.get("/api/auth/me", headers=headers)
    assert res.status_code == 401 and res.get_json()["error"] == "token_revoked"


def test_rate_limit_on_register():
    app = create_app("testing", overrides={"RATELIMIT_ENABLED": True})
    with app.app_context():
        db.create_all()
        c = app.test_client()
        codes = [c.post("/api/auth/register", json={}).status_code for _ in range(6)]
        db.drop_all()
    assert codes[:5] == [400] * 5 and codes[5] == 429


def test_create_admin_cli(app):
    runner = app.test_cli_runner()
    ok = runner.invoke(args=["create-admin", "--name", "Root Admin", "--email", "root@example.com", "--password", PASSWORD])
    assert ok.exit_code == 0, ok.output
    assert User.query.filter_by(email="root@example.com").one().role == "ADMIN"
    dup = runner.invoke(args=["create-admin", "--name", "Root Admin", "--email", "root@example.com", "--password", PASSWORD])
    assert dup.exit_code != 0
    weak = runner.invoke(args=["create-admin", "--name", "X Y", "--email", "x@example.com", "--password", "short"])
    assert weak.exit_code != 0
