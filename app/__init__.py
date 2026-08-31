from flask import Flask

from config.settings import settings


def create_app() -> Flask:
    """Create and configure the Business Assistant application."""
    app = Flask(__name__)

    app.config["ENVIRONMENT"] = settings.APP_ENV
    app.config["SECRET_KEY"] = settings.APP_SECRET_KEY

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "service": "ai-business-assistant",
            "environment": app.config["ENVIRONMENT"],
        }

    return app
