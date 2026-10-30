import pytest

from app import create_app
from app.extensions import db
from app.models.user import User


@pytest.fixture()
def app():
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


PASSWORD = "Passw0rd!x"


@pytest.fixture()
def make_user(app):
    def _make(role="CUSTOMER", email=None, status="ACTIVE", password=PASSWORD, name="Test User"):
        user = User(name=name, email=email or f"{role.lower()}@example.com", role=role, status=status)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user

    return _make


@pytest.fixture()
def login(client):
    def _login(email, password=PASSWORD):
        res = client.post("/api/auth/login", json={"email": email, "password": password})
        assert res.status_code == 200, res.get_json()
        return {"Authorization": f"Bearer {res.get_json()['access_token']}"}

    return _login
