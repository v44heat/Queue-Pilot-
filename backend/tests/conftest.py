import pytest

from app import create_app
from app.extensions import db
from app.models.counter import Counter, StaffCounterAssignment
from app.models.service import Service
from app.models.user import User


@pytest.fixture(autouse=True)
def fast_password_hashing(monkeypatch):
    """Tests create many users; use a cheap (still salted, real) hash so the suite stays fast."""
    from werkzeug.security import generate_password_hash

    monkeypatch.setattr("app.models.user.hash_password", lambda pw: generate_password_hash(pw, method="pbkdf2:sha256:1000"))


@pytest.fixture()
def app(tmp_path):
    app = create_app("testing", overrides={"ML_ARTIFACT_DIR": str(tmp_path / "artifacts")})
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()
        from app.services import ml_service

        ml_service.clear_model_cache()


@pytest.fixture()
def fast_models(monkeypatch):
    """Smaller ensembles so ML tests run quickly (same code path, fewer trees)."""
    from app.ml import training

    monkeypatch.setitem(training.RF_PARAMS, "n_estimators", 20)
    monkeypatch.setitem(training.GB_PARAMS, "n_estimators", 40)


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
def make_service(app):
    def _make(name="General Enquiry", prefix="GEN", duration=10, status="ACTIVE"):
        service = Service(name=name, prefix=prefix, default_service_duration=duration, status=status)
        db.session.add(service)
        db.session.commit()
        return service

    return _make


@pytest.fixture()
def make_counter(app):
    def _make(name="Counter 1", service=None, status="OPEN", staff=()):
        counter = Counter(name=name, service_id=service.id if service else None, status=status)
        db.session.add(counter)
        db.session.flush()
        for s in staff:
            db.session.add(StaffCounterAssignment(staff_id=s.id, counter_id=counter.id))
        db.session.commit()
        return counter

    return _make


@pytest.fixture()
def login(client):
    def _login(email, password=PASSWORD):
        res = client.post("/api/auth/login", json={"email": email, "password": password})
        assert res.status_code == 200, res.get_json()
        return {"Authorization": f"Bearer {res.get_json()['access_token']}"}

    return _login
