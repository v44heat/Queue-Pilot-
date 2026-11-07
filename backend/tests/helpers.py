"""Builders for analytics/report tests. Local time zone in tests is Africa/Nairobi (UTC+3, no DST)."""
from datetime import datetime, timedelta, timezone
from itertools import count

from app.extensions import db
from app.models.queue import QueueTicket

_n = count(5000)


def utc(y, m, d, h=0, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc)


def local(y, m, d, h=0, mi=0):
    """A moment given in Nairobi local time, as the UTC datetime that is stored."""
    return utc(y, m, d, h, mi) - timedelta(hours=3)


def add_ticket(make_user, service, status="WAITING", join=None, **fields):
    n = next(_n)
    join = join or datetime.now(timezone.utc)
    user = make_user("CUSTOMER", f"h{n}@example.com", name=f"Cust {n}")
    t = QueueTicket(queue_number=f"{service.prefix}-{n}", user_id=user.id, service_id=service.id,
                    queue_date=(join + timedelta(hours=3)).date(), sequence=n, status=status, join_time=join, **fields)
    db.session.add(t)
    db.session.commit()
    return t
