import pytest

from app.models.setting import SystemSetting
from app.services import congestion_service, settings_service
from app.services.notification_service import is_significant_change


@pytest.fixture()
def adm(client, make_user, login):
    make_user("ADMIN", "admin@example.com")
    make_user("CUSTOMER", "cust@example.com")
    return type("A", (), dict(h=login("admin@example.com"), hc=login("cust@example.com")))


def patch(client, h, **settings):
    return client.patch("/api/settings", json={"settings": settings}, headers=h)


def values(client, h):
    return {s["key"]: s["value"] for s in client.get("/api/settings", headers=h).get_json()["settings"]}


def test_defaults_are_listed_with_metadata(client, adm):
    items = client.get("/api/settings", headers=adm.h).get_json()["settings"]
    by_key = {s["key"]: s for s in items}
    assert by_key["congestion.moderate_min"]["value"] == 5 and by_key["congestion.high_min"]["value"] == 11 and by_key["congestion.critical_min"]["value"] == 21
    assert all(s["is_default"] and s["value"] == s["default"] and s["label"] and s["description"] for s in items)
    assert {s["group"] for s in items} == {"Congestion", "Customer notifications", "Counter recommendations"}


def test_update_applies_and_is_marked_non_default(client, adm):
    res = patch(client, adm.h, **{"congestion.moderate_min": 3, "congestion.high_min": 6, "congestion.critical_min": 9})
    assert res.status_code == 200
    by_key = {s["key"]: s for s in res.get_json()["settings"]}
    assert by_key["congestion.high_min"]["value"] == 6 and by_key["congestion.high_min"]["is_default"] is False
    assert by_key["congestion.high_min"]["updated_at"] is not None
    assert values(client, adm.h)["congestion.critical_min"] == 9


def test_changed_thresholds_change_congestion_levels_immediately(client, adm, app):
    assert congestion_service.level_for(6) == "MODERATE"
    patch(client, adm.h, **{"congestion.moderate_min": 2, "congestion.high_min": 4, "congestion.critical_min": 6})
    assert [congestion_service.level_for(n) for n in (1, 2, 3, 4, 5, 6)] == ["LOW", "MODERATE", "MODERATE", "HIGH", "HIGH", "CRITICAL"]
    assert congestion_service.thresholds() == {"moderate": 2, "high": 4, "critical": 6}


def test_changed_notification_thresholds_are_used(client, adm, app):
    assert is_significant_change(30, 25) is False and is_significant_change(10, 15) is False
    patch(client, adm.h, **{"notifications.wait_change_minutes": 3, "notifications.wait_change_ratio": 0.1})
    assert is_significant_change(30, 25) is True and is_significant_change(10, 15) is True
    assert is_significant_change(30, 29) is False  # still below the new minimum


@pytest.mark.parametrize("bad", [
    {"congestion.moderate_min": 0}, {"congestion.moderate_min": 1001}, {"congestion.moderate_min": "5"},
    {"congestion.moderate_min": True}, {"congestion.moderate_min": 5.5}, {"notifications.approaching_ahead": -1},
    {"notifications.wait_change_ratio": 0}, {"notifications.wait_change_minutes": 500}, {"no.such.setting": 1},
])
def test_invalid_values_are_rejected_and_nothing_changes(client, adm, bad):
    res = patch(client, adm.h, **bad)
    assert res.status_code == 400 and set(res.get_json()["details"]) == set(bad)
    assert SystemSetting.query.count() == 0


def test_congestion_thresholds_must_increase(client, adm):
    res = patch(client, adm.h, **{"congestion.high_min": 4})  # 4 <= moderate default 5
    assert res.status_code == 400 and "congestion.high_min" in res.get_json()["details"]
    res = patch(client, adm.h, **{"congestion.moderate_min": 30})  # 30 >= high default 11
    assert res.status_code == 400 and "congestion.high_min" in res.get_json()["details"]
    assert patch(client, adm.h, **{"congestion.moderate_min": 30, "congestion.high_min": 40, "congestion.critical_min": 50}).status_code == 200


def test_update_is_all_or_nothing(client, adm):
    res = patch(client, adm.h, **{"notifications.approaching_ahead": 4, "congestion.moderate_min": 0})
    assert res.status_code == 400
    assert values(client, adm.h)["notifications.approaching_ahead"] == 2  # the valid change was not applied either


def test_null_resets_to_default(client, adm):
    patch(client, adm.h, **{"notifications.approaching_ahead": 5})
    assert values(client, adm.h)["notifications.approaching_ahead"] == 5
    res = patch(client, adm.h, **{"notifications.approaching_ahead": None})
    assert res.status_code == 200 and values(client, adm.h)["notifications.approaching_ahead"] == 2
    assert SystemSetting.query.count() == 0


def test_corrupt_stored_value_falls_back_to_default(app):
    from app.extensions import db
    db.session.add(SystemSetting(setting_name="congestion.high_min", setting_value="not-a-number"))
    db.session.commit()
    assert settings_service.get("congestion.high_min") == 11


def test_bad_request_bodies(client, adm):
    for body in (None, {}, {"settings": {}}, {"settings": []}, {"congestion.high_min": 12}):
        res = client.patch("/api/settings", json=body, headers=adm.h) if body is not None else client.patch("/api/settings", data="x", headers=adm.h)
        assert res.status_code == 400, body


def test_approaching_threshold_setting_changes_who_is_notified(client, adm, make_user, make_service, make_counter, login):
    svc = make_service()
    staff = make_user("STAFF", "s@example.com")
    counter = make_counter("C1", svc, "OPEN", [staff])
    users = [make_user("CUSTOMER", f"u{i}@example.com") for i in range(4)]
    heads = [login(u.email) for u in users]
    for h in heads:
        client.post("/api/queue/join", json={"service_id": svc.id}, headers=h)
    patch(client, adm.h, **{"notifications.approaching_ahead": 0})  # only the customer who is next
    client.post(f"/api/staff/counters/{counter.id}/call-next", headers=login("s@example.com"))
    approaching = lambda h: [n for n in client.get("/api/notifications", headers=h).get_json()["notifications"] if n["type"] == "TURN_APPROACHING"]  # noqa: E731
    assert [len(approaching(h)) for h in heads] == [0, 1, 0, 0]
