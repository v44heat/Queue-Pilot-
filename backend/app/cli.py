"""Flask CLI commands (admin bootstrap, seed data)."""
import click
from flask import Flask

from .extensions import db
from .models.counter import Counter, StaffCounterAssignment
from .models.user import User
from .ml.synthetic import generate_dataset
from .services import ml_service
from .services.queue_service import QueueError
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

    @app.cli.command("ml-generate-data")
    @click.option("--rows", default=6000, show_default=True, type=int)
    @click.option("--seed", default=42, show_default=True, type=int)
    @click.option("--out", default="../data/synthetic_waiting_times.csv", show_default=True)
    def ml_generate_data(rows, seed, out):
        """Write a reproducible SYNTHETIC dataset (development/demo only) to a CSV file."""
        df = generate_dataset(rows, seed)
        df.to_csv(out, index=False)
        click.echo(f"Wrote {len(df)} synthetic rows to {out} (seed={seed}).")

    @app.cli.command("ml-train")
    @click.option("--source", type=click.Choice(["synthetic", "historical", "mixed"]), default="synthetic", show_default=True)
    @click.option("--rows", default=6000, show_default=True, type=int, help="Synthetic rows to generate.")
    @click.option("--seed", default=42, show_default=True, type=int)
    @click.option("--activate-best", is_flag=True, help="Activate the selected model after training.")
    def ml_train(source, rows, seed, activate_best):
        """Train Linear Regression, Random Forest and Gradient Boosting, compare them, and register the results."""
        try:
            versions = ml_service.train_run(source, rows, seed, activate_best)
        except QueueError as e:
            raise click.ClickException(e.message)
        first = versions[0].details
        split = first["split"]
        click.echo(f"Data: {source}, {first['rows']} usable rows. Split: {split['n_train']} train / "
                   f"{split['n_validation']} validation / {split['n_test']} test (chronological).")
        click.echo(f"{'Model':20s} {'Ver':5s} {'Val MAE':>8s} {'Test MAE':>9s} {'Test RMSE':>10s} {'Test R2':>8s}  Notes")
        for v in versions:
            notes = ", ".join(n for n, on in (("SELECTED", v.details["selected_in_run"]), ("ACTIVE", v.is_active),
                                              ("ineligible", not v.details["eligible"])) if on)
            click.echo(f"{v.model_name:20s} {v.version:5s} {v.details['validation']['mae']:8.3f} {v.mae:9.3f} {v.rmse:10.3f} {v.r2:8.3f}  {notes}")
        b = first["baseline"]
        click.echo(f"{'Baseline (rule)':20s} {'-':5s} {b['validation']['mae']:8.3f} {b['test']['mae']:9.3f} {b['test']['rmse']:10.3f} {b['test']['r2']:8.3f}")
        click.echo("Metrics are measured on held-out data. Synthetic scores do not describe real-world accuracy.")
