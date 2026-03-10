from flask import Flask
from app.extensions import db
from app.routes.search import search_bp


def create_app():
    app = Flask(__name__)

    # load config
    app.config.from_object("config.Config")

    # initialize extensions
    db.init_app(app)

    # register routes
    app.register_blueprint(search_bp)

    return app