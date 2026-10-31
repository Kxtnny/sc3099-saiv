"""
Configuration settings for SAIV Instructor Dashboard.
"""

import os

# Service URLs
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://localhost:9090")
GRAFANA_URL = os.getenv("GRAFANA_URL", "http://localhost:3001")
FACE_SERVICE_URL = os.getenv("FACE_SERVICE_URL", "http://localhost:8001")

# API Configuration
API_V1_PREFIX = "/api/v1"
API_BASE_URL = f"{BACKEND_URL.rstrip('/')}{API_V1_PREFIX}"

# Timeout defaults (in seconds)
DEFAULT_TIMEOUT = 10.0
EXPORT_TIMEOUT = 30.0

# Roles allowed to use the dashboard.
STAFF_ROLES = ["student", "ta", "instructor", "admin"]

# Existing Next.js check-in and device-registration portal.
STUDENT_PORTAL_URL = os.getenv("STUDENT_PORTAL_URL", "http://localhost:3000")

# Keep in sync with dashboard/prometheus-alert-rules.yml.
HIGH_FLAGGED_SHARE_THRESHOLD = 0.30
