"""User and token-blocklist models."""
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Index

from ..extensions import db
from ..utils.security import hash_password, verify_password

ROLES = ("CUSTOMER", "STAFF", "ADMIN")
STATUSES = ("ACTIVE", "INACTIVE")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="CUSTOMER")
    phone = db.Column(db.String(30))
    status = db.Column(db.String(20), nullable=False, default="ACTIVE")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        CheckConstraint("role IN ('CUSTOMER','STAFF','ADMIN')", name="ck_users_role"),
        CheckConstraint("status IN ('ACTIVE','INACTIVE')", name="ck_users_status"),
        Index("ix_users_role_status", "role", "status"),
    )

    def set_password(self, password: str) -> None:
        self.password_hash = hash_password(password)

    def check_password(self, password: str) -> bool:
        return verify_password(self.password_hash, password)

    @property
    def is_active(self) -> bool:
        return self.status == "ACTIVE"

    def to_dict(self) -> dict:
        """Public representation. Never includes the password hash."""
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "role": self.role,
            "phone": self.phone,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class TokenBlocklist(db.Model):
    """Revoked JWT ids (populated on logout)."""

    __tablename__ = "token_blocklist"

    id = db.Column(db.Integer, primary_key=True)
    jti = db.Column(db.String(64), nullable=False, unique=True, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
