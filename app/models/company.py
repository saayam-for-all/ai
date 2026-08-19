from app.extensions import db
from app.models.schema import DATABASE_SCHEMA


class Company(db.Model):
    __tablename__ = "companies"
    __table_args__ = {"schema": DATABASE_SCHEMA}

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.String(50), unique=True, nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False, index=True)
    description = db.Column(db.Text)
