from app.extensions import db


class Category(db.Model):
    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.String(50), unique=True, nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False, index=True)
    label = db.Column(db.String(255), nullable=True, index=True)
    description = db.Column(db.Text)