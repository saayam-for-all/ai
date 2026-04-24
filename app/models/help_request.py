from app.extensions import db


class HelpRequest(db.Model):
    __tablename__ = "request"
    __table_args__ = {"schema": "virginia_dev_saayam_rdbms"}

    req_id = db.Column(db.String(50), primary_key=True, index=True)
    req_user_id = db.Column(db.String(50), nullable=False, index=True)
    req_cat_id = db.Column(db.String(50), index=True)
    req_subj = db.Column(db.String(255), index=True)
    req_desc = db.Column(db.Text)
    req_status_id = db.Column(db.Integer, index=True)
    to_public = db.Column(db.Boolean, default=False, nullable=False)
