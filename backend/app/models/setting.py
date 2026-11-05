"""Administrator-editable system settings (key/value)."""
from ..extensions import db
from .user import utcnow


class SystemSetting(db.Model):
    __tablename__ = "system_settings"

    id = db.Column(db.Integer, primary_key=True)
    setting_name = db.Column(db.String(80), nullable=False, unique=True)
    setting_value = db.Column(db.Text, nullable=False)  # parsed and validated by settings_service
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
