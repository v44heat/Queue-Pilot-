"""Flask CLI commands (admin bootstrap, seed data)."""
import click
from flask import Flask

from .extensions import db
from .models.counter import Counter, StaffCounterAssignment
from .models.user import User
from .services.seed import seed_counters, seed_services
from .utils.validation import validate_new_user


def register_cli(app: Flask) -> None:
    @app.cli.command("create-admin")
    @click.option("--name", prompt=True)
    @click.option("--email", prompt=True)
    @click.option("--phone", default=None)
    @click.password_option()
    def create_admin(name, email, phone, password):
        """Create an ADMIN account. Public registration can never create admins."""
        clean, errors = validate_new_user(
            {"name": name, "email": email, "password": password, "phone": phone, "role": "ADMIN"},
            allow_role=True,
        )
        if errors:
            raise click.ClickException("; ".join(f"{k}: {v}" for k, v in errors.items()))
        if User.query.filter_by(email=clean["email"]).first():
            raise click.ClickException("A user with that email already exists.")
        user = User(name=clean["name"], email=clean["email"], phone=clean["phone"], role="ADMIN")
        user.set_password(clean["password"])
        db.session.add(user)
        db.session.commit()
        click.echo(f"Admin created: {user.email} (id={user.id})")

    @app.cli.command("seed-services")
    def seed_services_command():
        """Create the default demo services (idempotent)."""
        click.echo(f"Created {seed_services()} service(s).")

    @app.cli.command("seed-counters")
    def seed_counters_command():
        """Create one closed counter per active service (idempotent)."""
        click.echo(f"Created {seed_counters()} counter(s).")

    @app.cli.command("assign-staff")
    @click.option("--email", required=True, help="Email of an existing STAFF account.")
    @click.option("--counter-id", required=True, type=int)
    def assign_staff_command(email, counter_id):
        """Assign a staff member to a counter."""
        staff = User.query.filter_by(email=email.strip().lower()).first()
        if staff is None or staff.role != "STAFF":
            raise click.ClickException("No STAFF account with that email.")
        counter = db.session.get(Counter, counter_id)
        if counter is None:
            raise click.ClickException("No counter with that id.")
        if StaffCounterAssignment.query.filter_by(staff_id=staff.id, counter_id=counter.id).first():
            raise click.ClickException("Already assigned.")
        db.session.add(StaffCounterAssignment(staff_id=staff.id, counter_id=counter.id))
        db.session.commit()
        click.echo(f"Assigned {staff.email} to {counter.name}.")
