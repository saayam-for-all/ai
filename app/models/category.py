from app.extensions import db
from app.models.schema import DATABASE_SCHEMA


class Category(db.Model):
    __tablename__ = "help_categories"
    __table_args__ = {"schema": DATABASE_SCHEMA}

    cat_id = db.Column(db.String(50), primary_key=True, index=True)
    cat_name = db.Column(db.String(255), nullable=False, index=True)
    cat_desc = db.Column(db.Text)
