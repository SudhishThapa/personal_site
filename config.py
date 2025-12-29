
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret")

    # Use DATABASE_URL from environment (Postgres on Render)
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL")
    assert SQLALCHEMY_DATABASE_URI, "DATABASE_URL must be set"

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    UPLOAD_FOLDER = os.path.join("static", "uploads")
    MAX_CONTENT_LENGTH = 100 * 1024 * 1024  # 100 MB

    ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
    ALLOWED_VIDEO_EXTENSIONS = {"mp4", "webm", "ogg", "mov", "m4v"}

    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")

