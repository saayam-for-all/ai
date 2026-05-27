from flask import Flask
from app.extensions import db
from app.routes.search import search_bp
from app.routes.suggestions import suggestions_bp


def create_app():
    app = Flask(__name__)

    app.config.from_object("config.Config")

    db.init_app(app)

    from app.models import user, help_request, organization, category, company  # noqa: F401

    api_prefix = app.config.get("API_URL_PREFIX", "/api")
    app.register_blueprint(search_bp, url_prefix=api_prefix)
    app.register_blueprint(suggestions_bp, url_prefix=api_prefix)

    return app