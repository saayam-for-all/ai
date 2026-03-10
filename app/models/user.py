from app.extensions import db


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(50), unique=True, nullable=False, index=True)
    full_name = db.Column(db.String(255), nullable=False, index=True)
    username = db.Column(db.String(255), unique=True, nullable=False, index=True)
    role = db.Column(db.String(50), nullable=False, index=True)
    organization_id = db.Column(db.Integer, nullable=True, index=True)