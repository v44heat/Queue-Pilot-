"""QueuePilot application factory."""
import logging
import os

from flask import Flask, jsonify

from .config import CONFIG_MAP
from .extensions import cors, db, jwt, limiter, migrate


def create_app(config_name: str | None = None, overrides: dict | None = None) -> Flask:
    config_name = config_name or os.environ.get("FLASK_ENV", "development")
    config_class = CONFIG_MAP.get(config_name, CONFIG_MAP["development"])

    app = Flask(__name__)
    app.config.from_object(config_class)
    if overrides:
        app.config.update(overrides)

    missing = [
        k for k in ("SECRET_KEY", "JWT_SECRET_KEY", "SQLALCHEMY_DATABASE_URI")
        if not app.config.get(k)
    ]
    if missing:
        raise RuntimeError(
            "Missing required configuration: "
            + ", ".join(missing)
            + ". Copy .env.example to .env and fill in the values."
        )

    _configure_logging(app)

    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)
    cors.init_app(app, resources={r"/api/*": {"origins": app.config["CORS_ORIGINS"]}})
    limiter.init_app(app)
    limiter.default_limits = [app.config["RATELIMIT_DEFAULT"]]

    from . import models  # noqa: F401  (register models with SQLAlchemy metadata)
    from .cli import register_cli
    from .routes.auth import auth_bp
    from .routes.health import health_bp
    from .routes.users import users_bp
    from .utils.auth import register_jwt_handlers

    register_jwt_handlers()
    app.register_blueprint(health_bp, url_prefix="/api")
    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(users_bp, url_prefix="/api/users")
    register_cli(app)

    _register_error_handlers(app)
    return app


def _configure_logging(app: Flask) -> None:
    level = logging.DEBUG if app.debug else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app.logger.setLevel(level)


def _register_error_handlers(app: Flask) -> None:
    @app.errorhandler(404)
    def not_found(_e):
        return jsonify(error="not_found", message="Resource not found."), 404

    @app.errorhandler(405)
    def method_not_allowed(_e):
        return jsonify(error="method_not_allowed", message="Method not allowed."), 405

    @app.errorhandler(429)
    def rate_limited(_e):
        return jsonify(error="rate_limited", message="Too many requests. Please slow down."), 429

    @app.errorhandler(500)
    def server_error(_e):
        return jsonify(error="server_error", message="An unexpected error occurred."), 500
