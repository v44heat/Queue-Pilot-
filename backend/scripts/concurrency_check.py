"""Real multi-threaded check of queue-joining under concurrency.

Run from backend/ against your DEVELOPMENT PostgreSQL database (after `flask db upgrade`):

    python scripts/concurrency_check.py --customers 30

It creates a temporary service and temporary customers, fires simultaneous join requests
through the same business logic the API uses, verifies the results, then deletes everything
it created. Exit code 0 = all checks passed.
"""
import argparse
import os
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models.queue import QueueCounter, QueueTicket  # noqa: E402
from app.models.service import Service  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.queue_service import QueueError, join_queue  # noqa: E402

PREFIX = "ZZC"


def run_threads(app, jobs):
    """Run callables simultaneously; return their results/exceptions in order."""
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
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return out


def cleanup(app):
    with app.app_context():
        svc = Service.query.filter_by(prefix=PREFIX).first()
        if svc:
            QueueTicket.query.filter_by(service_id=svc.id).delete()
            QueueCounter.query.filter_by(service_id=svc.id).delete()
            db.session.delete(svc)
        User.query.filter(User.email.like("zzc-%@concurrency.test")).delete(synchronize_session=False)
        db.session.commit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--customers", type=int, default=30)
    n = parser.parse_args().customers

    app = create_app()
    cleanup(app)  # clear leftovers from an interrupted earlier run
    failures = []
    try:
        with app.app_context():
            svc = Service(name="Concurrency Check", prefix=PREFIX, default_service_duration=5)
            db.session.add(svc)
            ids = []
            for i in range(n + 1):
                u = User(name=f"ZZC {i}", email=f"zzc-{i}@concurrency.test", password_hash="x", role="CUSTOMER")
                db.session.add(u)
                db.session.flush()
                ids.append(u.id)
            db.session.commit()
            service_id = svc.id

        def joiner(uid):
            def job():
                u = db.session.get(User, uid)
                return join_queue(u, service_id).queue_number
            return job

        # 1) N different customers join at the same instant.
        res = run_threads(app, [joiner(uid) for uid in ids[:n]])
        crashes = [r for r in res if r[0] != "ok"]
        numbers = sorted(r[1] for r in res if r[0] == "ok")
        expected = [f"{PREFIX}-{k:03d}" for k in range(1, n + 1)]
        print(f"[1] {n} simultaneous joins -> {len(numbers)} tickets, {len(crashes)} errors")
        if crashes:
            failures.append(f"unexpected errors: {crashes[:3]}")
        if numbers != expected:
            failures.append("ticket numbers are not unique and gap-free")

        # 2) ONE customer fires 10 simultaneous joins: exactly one may succeed.
        dup_user = ids[n]
        res = run_threads(app, [joiner(dup_user) for _ in range(10)])
        ok = [r for r in res if r[0] == "ok"]
        dup = [r for r in res if r == ("queue_error", "already_in_queue")]
        print(f"[2] 10 simultaneous joins by one customer -> {len(ok)} created, {len(dup)} rejected as duplicates")
        if len(ok) != 1 or len(dup) != 9:
            failures.append(f"duplicate protection failed: {res}")

        with app.app_context():
            total = QueueTicket.query.filter_by(service_id=service_id).count()
        if total != n + 1:
            failures.append(f"expected {n + 1} tickets in the database, found {total}")
    finally:
        cleanup(app)

    if failures:
        print("FAILED:\n - " + "\n - ".join(failures))
        sys.exit(1)
    print("PASSED: numbers unique and gap-free; duplicate active tickets prevented.")


if __name__ == "__main__":
    main()
