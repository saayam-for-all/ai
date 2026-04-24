from app.extensions import db


class Organization(db.Model):
    __tablename__ = "organizations"
    __table_args__ = {"schema": "virginia_dev_saayam_rdbms"}

    org_id = db.Column(db.String(50), primary_key=True, index=True)
    org_name = db.Column(db.String(255), nullable=False, index=True)
    mission = db.Column(db.Text)
    email = db.Column(db.String(255))
    phone = db.Column(db.String(50))
