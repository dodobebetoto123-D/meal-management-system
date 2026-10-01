import os
from zoneinfo import ZoneInfo

from flask import Flask

from .db import close_db, init_db


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        DATABASE=os.path.join(app.instance_path, "meals.sqlite3"),
        TIMEZONE=os.environ.get("MEAL_TIMEZONE", "Asia/Seoul"),
        SESSION_TTL_SECONDS=8 * 60 * 60,
        ADMIN_USERNAME=os.environ.get("ADMIN_USERNAME"),
        ADMIN_PASSWORD=os.environ.get("ADMIN_PASSWORD"),
    )
    if test_config:
        app.config.update(test_config)
    os.makedirs(app.instance_path, exist_ok=True)
    try:
        ZoneInfo(app.config["TIMEZONE"])
    except Exception as exc:
        raise ValueError("TIMEZONE must be a valid IANA timezone") from exc

    app.register_blueprint(api, url_prefix="/api")
    app.teardown_appcontext(close_db)
    with app.app_context():
        init_db()
    return app


def configured_timezone(app):
    return ZoneInfo(app.config["TIMEZONE"])


from .routes import api  # noqa: E402
