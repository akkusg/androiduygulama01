from app.routes.admin import admin_bp
from app.routes.auth import auth_bp
from app.routes.dashboard import dashboard_bp
from app.routes.devices import devices_bp
from app.routes.health import health_bp
from app.routes.job_applications import job_applications_bp
from app.routes.job_postings import job_postings_bp
from app.routes.users import users_bp
from app.routes.videos import videos_bp
from app.routes.worker_support import worker_support_bp

__all__ = [
    "auth_bp",
    "admin_bp",
    "dashboard_bp",
    "devices_bp",
    "health_bp",
    "job_applications_bp",
    "job_postings_bp",
    "users_bp",
    "videos_bp",
    "worker_support_bp",
]
