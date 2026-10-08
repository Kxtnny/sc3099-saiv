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

# Allowed dashboard roles
STAFF_ROLES = ["instructor", "admin", "ta"]

