from app.extensions import db


class HelpRequest(db.Model):
    __tablename__ = "help_requests"

    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.String(50), unique=True, nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False, index=True)
    description = db.Column(db.Text)
    created_by = db.Column(db.Integer, nullable=False, index=True)
    assigned_volunteer_id = db.Column(db.Integer, nullable=True, index=True)
    organization_id = db.Column(db.Integer, nullable=True, index=True)
    category_id = db.Column(db.Integer, nullable=True, index=True)
    admin_scope_id = db.Column(db.Integer, nullable=True, index=True)
    is_public = db.Column(db.Boolean, default=False, nullable=False)