from flask import Flask


def create_app() -> Flask:
    """Create and configure the Business Assistant application."""
    app = Flask(__name__)

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "service": "ai-business-assistant"
        }

    return app
