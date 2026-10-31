"""Flask CLI commands (admin bootstrap, seed data)."""
import click
from flask import Flask

from .extensions import db
from .models.user import User
from .services.seed import seed_services
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
