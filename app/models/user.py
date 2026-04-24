from app.extensions import db


class User(db.Model):
    __tablename__ = "users"
    __table_args__ = {"schema": "virginia_dev_saayam_rdbms"}

    user_id = db.Column(db.String(50), primary_key=True, index=True)
    full_name = db.Column(db.String(255), nullable=False, index=True)
    primary_email_address = db.Column(db.String(255), index=True)
    user_category_id = db.Column(db.Integer, index=True)
    state_id = db.Column(db.String(50))
    country_id = db.Column(db.Integer)
    user_status_id = db.Column(db.BigInteger)
