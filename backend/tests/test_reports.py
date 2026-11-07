import csv
import io

import pytest

from app.extensions import db
from app.models.counter import CounterSession
from app.models.ml import ModelVersion
from app.utils.csv_export import safe_cell

from .helpers import add_ticket, local


@pytest.fixture()
def rp(client, make_user, make_service, make_counter, login):
    gen = make_service()
    staff = make_user("STAFF", "staff@example.com")
    make_user("ADMIN", "admin@example.com")
    make_user("CUSTOMER", "plain@example.com")
    c1 = make_counter("GEN 1", gen, "OPEN", [staff])
    return type("R", (), dict(gen=gen, c1=c1, mk=make_user, ms=make_service, h=login("admin@example.com"), hs=login("staff@example.com"), hc=login("plain@example.com")))


def parse(res):
    assert res.status_code == 200, res.get_data(as_text=True)
    text = res.get_data(as_text=True)
    assert text.startswith("\ufeff")  # BOM so spreadsheet programs read UTF-8 correctly
    rows = list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))
    return rows[0], [dict(zip(rows[0], r)) for r in rows[1:]]


REPORTS = ["daily", "weekly", "monthly", "services", "counters", "models"]


@pytest.mark.parametrize("name", REPORTS)
def test_reports_are_admin_only(client, rp, name):
    url = f"/api/reports/{name}"
    assert client.get(url).status_code == 401
    assert client.get(url, headers=rp.hs).status_code == 403
    assert client.get(url, headers=rp.hc).status_code == 403
    assert client.get(url, headers=rp.h).status_code == 200


# ------------------------------------------------------------------ daily / weekly / monthly
def seed(rp):
    add_ticket(rp.mk, rp.gen, "COMPLETED", join=local(2026, 3, 2, 9), actual_waiting_time=10.0, service_duration=4.0)
    add_ticket(rp.mk, rp.gen, "COMPLETED", join=local(2026, 3, 2, 10), actual_waiting_time=20.0, service_duration=8.0)
    add_ticket(rp.mk, rp.gen, "CANCELLED", join=local(2026, 3, 2, 11))
    add_ticket(rp.mk, rp.gen, "SKIPPED", join=local(2026, 3, 8, 9))  # Sunday of the same week
    add_ticket(rp.mk, rp.gen, "ABSENT", join=local(2026, 3, 9, 9))  # next Monday
    add_ticket(rp.mk, rp.gen, "COMPLETED", join=local(2026, 4, 1, 9), actual_waiting_time=1.0, service_duration=1.0)


def test_daily_report_contains_that_days_records(client, rp):
    seed(rp)
    res = client.get("/api/reports/daily?date=2026-03-02", headers=rp.h)
    assert res.mimetype == "text/csv" and 'filename="queuepilot-daily-2026-03-02.csv"' in res.headers["Content-Disposition"]
    header, rows = parse(res)
    assert header[:4] == ["Date", "Service", "Prefix", "Tickets joined"]
    assert len(rows) == 1
    r = rows[0]
    assert r["Date"] == "2026-03-02" and r["Service"] == "General Enquiry" and r["Prefix"] == "GEN"
    assert (r["Tickets joined"], r["Completed"], r["Cancelled"], r["Skipped"], r["Absent"]) == ("3", "2", "1", "0", "0")
    assert (r["Average waiting (min)"], r["Longest waiting (min)"], r["Average service (min)"]) == ("15.0", "20.0", "6.0")


def test_weekly_report_covers_monday_to_sunday_of_the_given_date(client, rp):
    seed(rp)
    res = client.get("/api/reports/weekly?date=2026-03-05", headers=rp.h)  # a Thursday
    assert 'filename="queuepilot-weekly-2026-03-02.csv"' in res.headers["Content-Disposition"]
    _, rows = parse(res)
    assert [r["Date"] for r in rows] == ["2026-03-02", "2026-03-08"]  # Mon 9th and April are outside


def test_monthly_report(client, rp):
    seed(rp)
    res = client.get("/api/reports/monthly?month=2026-03", headers=rp.h)
    assert 'filename="queuepilot-monthly-2026-03.csv"' in res.headers["Content-Disposition"]
    _, rows = parse(res)
    assert [r["Date"] for r in rows] == ["2026-03-02", "2026-03-08", "2026-03-09"]
    assert sum(int(r["Tickets joined"]) for r in rows) == 5


def test_empty_period_gives_only_the_header(client, rp):
    header, rows = parse(client.get("/api/reports/daily?date=2020-01-01", headers=rp.h))
    assert len(header) == 12 and rows == []


@pytest.mark.parametrize("url", ["/api/reports/daily?date=nope", "/api/reports/weekly?date=2026-99-99", "/api/reports/monthly?month=2026-13",
                                 "/api/reports/monthly?month=March", "/api/reports/services?days=0", "/api/reports/counters?from=2026-03-05&to=2026-03-01"])
def test_bad_report_parameters_are_rejected_as_json_errors(client, rp, url):
    res = client.get(url, headers=rp.h)
    assert res.status_code == 400 and res.get_json()["error"] == "validation_error"


# ------------------------------------------------------------------ service / counter / model reports
def test_service_report_matches_the_analytics_numbers(client, rp):
    seed(rp)
    _, rows = parse(client.get("/api/reports/services?from=2026-03-02&to=2026-03-09", headers=rp.h))
    g = next(r for r in rows if r["Prefix"] == "GEN")
    assert (g["Tickets joined"], g["Completed"], g["Cancelled"], g["Skipped"], g["Absent"]) == ("5", "2", "1", "1", "1")
    assert g["Completion rate (0-1)"] == "0.4"
    api = client.get("/api/analytics/service-performance?from=2026-03-02&to=2026-03-09", headers=rp.h).get_json()["services"][0]
    assert api["joined"] == int(g["Tickets joined"]) and api["completion_rate"] == float(g["Completion rate (0-1)"])


def test_counter_report(client, rp):
    db.session.add(CounterSession(counter_id=rp.c1.id, opened_at=local(2026, 3, 2, 8), closed_at=local(2026, 3, 2, 12)))
    db.session.commit()
    add_ticket(rp.mk, rp.gen, "COMPLETED", join=local(2026, 3, 2, 8, 50), counter_id=rp.c1.id, service_start_time=local(2026, 3, 2, 9),
               service_end_time=local(2026, 3, 2, 10), service_duration=60.0)
    _, rows = parse(client.get("/api/reports/counters?from=2026-03-02&to=2026-03-02", headers=rp.h))
    r = rows[0]
    assert r["Counter"] == "GEN 1" and r["Open (min)"] == "240.0" and r["Serving (min)"] == "60.0" and r["Utilization (0-1)"] == "0.25" and r["Customers served"] == "1"


def test_model_report_lists_measured_metrics_and_baseline(client, rp):
    db.session.add(ModelVersion(
        model_name="Random Forest", version="1.0", run_id="r1", model_path="r1/rf.joblib", data_source="synthetic", mae=5.1, rmse=8.2, r2=0.91, is_active=True,
        details={"eligible": True, "selected_in_run": True, "rows": 6000, "seed": 42, "validation": {"mae": 5.4, "rmse": 8.5, "r2": 0.9},
                 "baseline": {"test": {"mae": 8.3, "rmse": 13.5, "r2": 0.82}}}))
    db.session.commit()
    _, rows = parse(client.get("/api/reports/models", headers=rp.h))
    r = rows[0]
    assert (r["Model"], r["Version"], r["Training data"], r["Active"], r["Eligible"]) == ("Random Forest", "1.0", "synthetic", "yes", "yes")
    assert (r["Test MAE (min)"], r["Test RMSE (min)"], r["Test R2"], r["Validation MAE (min)"]) == ("5.1", "8.2", "0.91", "5.4")
    assert (r["Baseline test MAE (min)"], r["Usable rows"], r["Seed"]) == ("8.3", "6000", "42")


def test_model_report_with_no_models_is_just_a_header(client, rp):
    header, rows = parse(client.get("/api/reports/models", headers=rp.h))
    assert "Model" in header and rows == []


# ------------------------------------------------------------------ CSV injection
@pytest.mark.parametrize("value", ["=HYPERLINK(\"http://evil\",\"x\")", "+1+1", "-2+3", "@SUM(A1)", "\t=1", "\r=1"])
def test_formula_like_text_is_neutralised(value):
    assert safe_cell(value) == "'" + value


def test_safe_cell_leaves_normal_values_alone():
    assert safe_cell("General Enquiry") == "General Enquiry" and safe_cell(7) == 7 and safe_cell(-3.5) == -3.5
    assert safe_cell(None) == "" and safe_cell(True) == "yes" and safe_cell(False) == "no" and safe_cell("Zoë Café") == "Zoë Café"


def test_a_malicious_service_name_cannot_inject_a_formula_into_reports(client, rp):
    evil = rp.ms("=cmd|' /C calc'!A0", "EVL")
    add_ticket(rp.mk, evil, "COMPLETED", join=local(2026, 3, 2, 9), actual_waiting_time=1.0, service_duration=1.0)
    for url in ("/api/reports/daily?date=2026-03-02", "/api/reports/services?from=2026-03-02&to=2026-03-02"):
        _, rows = parse(client.get(url, headers=rp.h))
        names = [r["Service"] for r in rows]
        assert "'=cmd|' /C calc'!A0" in names and not any(n.startswith("=") for n in names)
