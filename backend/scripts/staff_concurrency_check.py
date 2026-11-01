"""Real multi-threaded check of staff calling under concurrency.

Run from backend/ against your DEVELOPMENT PostgreSQL database (after `flask db upgrade`):

    python scripts/staff_concurrency_check.py --counters 8

Scenario 1: N counters (each with its own staff member) call the next customer at the same
instant while N+4 customers wait. Every call must succeed with a DIFFERENT ticket, and the
tickets called must be exactly the first N in line.
Scenario 2: several staff members share ONE counter and all call at once; exactly one may
succeed (a counter never holds two customers).
Creates temporary data and deletes it afterwards. Exit code 0 = all checks passed.
"""
import argparse
import os
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models.counter import Counter, StaffCounterAssignment  # noqa: E402
from app.models.queue import QueueCounter, QueueTicket  # noqa: E402
from app.models.service import Service  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.queue_service import QueueError, join_queue  # noqa: E402
from app.services.staff_service import call_next  # noqa: E402

PREFIX = "ZZS"
EMAIL_LIKE = "zzs-%@concurrency.test"


def run_threads(app, jobs):
    barrier = threading.Barrier(len(jobs))
    out = [None] * len(jobs)

    def wrap(i, job):
        with app.app_context():
            barrier.wait()
            try:
                out[i] = ("ok", job())
            except QueueError as e:
                out[i] = ("queue_error", e.code)
            except Exception as e:  # noqa: BLE001
                out[i] = ("crash", repr(e))
            finally:
                db.session.remove()

    threads = [threading.Thread(target=wrap, args=(i, j)) for i, j in enumerate(jobs)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    return out


def cleanup(app):
    with app.app_context():
        svc = Service.query.filter_by(prefix=PREFIX).first()
        if svc:
            QueueTicket.query.filter_by(service_id=svc.id).delete()
            QueueCounter.query.filter_by(service_id=svc.id).delete()
            for c in Counter.query.filter_by(service_id=svc.id).all():
                StaffCounterAssignment.query.filter_by(counter_id=c.id).delete()
                db.session.delete(c)
            db.session.delete(svc)
        User.query.filter(User.email.like(EMAIL_LIKE)).delete(synchronize_session=False)
        db.session.commit()


def new_user(i, role):
    u = User(name=f"ZZS {role} {i}", email=f"zzs-{role.lower()}-{i}@concurrency.test", password_hash="x", role=role)
    db.session.add(u)
    db.session.flush()
    return u


def caller(staff_id, counter_id):
    def job():
        return call_next(db.session.get(User, staff_id), counter_id).queue_number
    return job


def main():
    n = argparse.ArgumentParser()
    n.add_argument("--counters", type=int, default=8)
    n = n.parse_args().counters

    app = create_app()
    cleanup(app)
    failures = []
    try:
        with app.app_context():
            svc = Service(name="Staff Concurrency Check", prefix=PREFIX, default_service_duration=5)
            db.session.add(svc)
            db.session.flush()
            staff_ids, counter_ids = [], []
            for i in range(n):
                s = new_user(i, "STAFF")
                c = Counter(name=f"ZZS Counter {i}", service_id=svc.id, status="OPEN")
                db.session.add(c)
                db.session.flush()
                db.session.add(StaffCounterAssignment(staff_id=s.id, counter_id=c.id))
                staff_ids.append(s.id)
                counter_ids.append(c.id)
            customers = [new_user(i, "CUSTOMER") for i in range(n + 4)]
            db.session.commit()
            service_id = svc.id
            customer_ids = [u.id for u in customers]
            for uid in customer_ids:  # sequential joins define the line order
                join_queue(db.session.get(User, uid), service_id)

        res = run_threads(app, [caller(s, c) for s, c in zip(staff_ids, counter_ids)])
        errors = [r for r in res if r[0] != "ok"]
        called = [r[1] for r in res if r[0] == "ok"]
        expected = {f"{PREFIX}-{k:03d}" for k in range(1, n + 1)}
        print(f"[1] {n} counters called simultaneously -> {len(called)} calls, {len(errors)} errors, {len(set(called))} distinct tickets")
        if errors:
            failures.append(f"unexpected errors: {errors[:3]}")
        if len(set(called)) != len(called):
            failures.append("the same ticket was called twice")
        if set(called) != expected:
            failures.append(f"called tickets are not the first {n} in line: {sorted(called)}")

        # Scenario 2: several staff on a single counter (fresh counter, others stay busy).
        with app.app_context():
            shared = Counter(name="ZZS Shared", service_id=service_id, status="OPEN")
            db.session.add(shared)
            db.session.flush()
            shared_staff = [new_user(100 + i, "STAFF") for i in range(6)]
            for s in shared_staff:
                db.session.add(StaffCounterAssignment(staff_id=s.id, counter_id=shared.id))
            db.session.commit()
            shared_id, shared_staff_ids = shared.id, [s.id for s in shared_staff]
        res = run_threads(app, [caller(s, shared_id) for s in shared_staff_ids])
        ok = [r for r in res if r[0] == "ok"]
        busy = [r for r in res if r == ("queue_error", "counter_busy")]
        print(f"[2] 6 staff on one counter called simultaneously -> {len(ok)} succeeded, {len(busy)} rejected as busy")
        if len(ok) != 1 or len(busy) != 5:
            failures.append(f"counter double-booking protection failed: {res}")
        with app.app_context():
            held = QueueTicket.query.filter_by(counter_id=shared_id).filter(QueueTicket.status.in_(("CALLED", "SERVING"))).count()
        if held != 1:
            failures.append(f"shared counter holds {held} customers")
    finally:
        cleanup(app)

    if failures:
        print("FAILED:\n - " + "\n - ".join(failures))
        sys.exit(1)
    print("PASSED: distinct tickets for simultaneous callers; a counter never holds two customers.")


if __name__ == "__main__":
    main()
