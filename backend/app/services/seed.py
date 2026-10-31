"""Idempotent seed data."""
from ..extensions import db
from ..models.service import Service

# Default durations (minutes) are starting estimates for the demo, editable by admins later.
DEFAULT_SERVICES = [
    ("General Enquiry", "GEN", 10, "Questions and general assistance."),
    ("Payments", "PAY", 6, "Fee payments and receipts."),
    ("Registration", "REG", 12, "New registrations and form submission."),
    ("Technical Support", "TEC", 15, "Help with technical or account problems."),
    ("Document Collection", "DOC", 5, "Collect completed documents."),
]


def seed_services() -> int:
    """Create any missing default services. Returns how many were created."""
    created = 0
    for name, prefix, duration, description in DEFAULT_SERVICES:
        if Service.query.filter((Service.name == name) | (Service.prefix == prefix)).first():
            continue
        db.session.add(Service(name=name, prefix=prefix, default_service_duration=duration, description=description))
        created += 1
    db.session.commit()
    return created
