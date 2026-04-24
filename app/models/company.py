from app.extensions import db


class Company(db.Model):
    __tablename__ = "companies"
    __table_args__ = {"schema": "virginia_dev_saayam_rdbms"}

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.String(50), unique=True, nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False, index=True)
    description = db.Column(db.Text)
