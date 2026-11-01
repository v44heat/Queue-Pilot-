"""Staff endpoints (STAFF role only; administrators cannot bypass counter workflows)."""
from flask import Blueprint, g, jsonify

from ..services import counter_service as cs
from ..services import staff_service as ss
from ..services.queue_service import serialize_ticket_for_staff
from ..utils.auth import roles_required

staff_bp = Blueprint("staff", __name__)


def _counter_payload(counter):
    return jsonify(counter=cs.serialize_counter(counter))


@staff_bp.get("/counters")
@roles_required("STAFF")
def my_counters():
    return jsonify(counters=[cs.serialize_counter(c) for c in ss.assigned_counters(g.current_user)])


@staff_bp.get("/counters/<int:counter_id>/queue")
@roles_required("STAFF")
def counter_queue(counter_id: int):
    counter = ss.get_assigned_counter(g.current_user, counter_id)
    return jsonify(
        counter=cs.serialize_counter(counter),
        waiting=[serialize_ticket_for_staff(t) for t in ss.waiting_list(counter)],
        stats=cs.counter_stats(counter),
    )


@staff_bp.post("/counters/<int:counter_id>/open")
@roles_required("STAFF")
def open_counter(counter_id: int):
    return _counter_payload(ss.open_counter(g.current_user, counter_id))


@staff_bp.post("/counters/<int:counter_id>/close")
@roles_required("STAFF")
def close_counter(counter_id: int):
    return _counter_payload(ss.close_counter(g.current_user, counter_id))


@staff_bp.post("/counters/<int:counter_id>/call-next")
@roles_required("STAFF")
def call_next(counter_id: int):
    ticket = ss.call_next(g.current_user, counter_id)
    return jsonify(ticket=serialize_ticket_for_staff(ticket))


def _ticket_action(fn):
    def view(ticket_id: int):
        return jsonify(ticket=serialize_ticket_for_staff(fn(g.current_user, ticket_id)))
    view.__name__ = fn.__name__
    return roles_required("STAFF")(view)


staff_bp.add_url_rule("/tickets/<int:ticket_id>/start", view_func=_ticket_action(ss.start_service), methods=["POST"])
staff_bp.add_url_rule("/tickets/<int:ticket_id>/complete", view_func=_ticket_action(ss.complete_service), methods=["POST"])
staff_bp.add_url_rule("/tickets/<int:ticket_id>/skip", view_func=_ticket_action(ss.skip_ticket), methods=["POST"])
staff_bp.add_url_rule("/tickets/<int:ticket_id>/absent", view_func=_ticket_action(ss.mark_absent), methods=["POST"])
