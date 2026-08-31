import os

from dotenv import load_dotenv


load_dotenv()


class Settings:
    """Application configuration loaded from environment variables."""

    APP_ENV = os.getenv("APP_ENV", "development")
    APP_SECRET_KEY = os.getenv("APP_SECRET_KEY", "")


settings = Settings()
