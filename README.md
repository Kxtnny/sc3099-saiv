# SAIV - Secure Attendance & Identity Verification

## NTU Computer Science Capstone Project - Student Package

Welcome to the SAIV capstone project! Your team will build a secure, privacy-preserving attendance system resistant to deepfakes, replay attacks, and remote sign-ins.

---

## Project Overview

### Learning Objectives
- Full-stack development (PWA frontend, REST API, database design)
- Security engineering (liveness detection, device binding, geofencing)
- Privacy-first architecture (PII minimization, encrypted storage)
- ML integration (pre-trained face recognition models)
- DevOps (Docker, observability)

### Project Scope
- **Duration**: 12-14 weeks
- **Team Size**: 4 students (1 per module)
- **Grading**: 130 points total (90 public + 40 hidden)

---

## Architecture

Your team will implement 4 modules:

### Module 1: Student Frontend PWA
**Recommended Tech Stack**: React/Next.js, TypeScript, WebRTC
- Student check-in interface
- Camera access for liveness challenges
- Geolocation with consent
- Device binding (public key rotation)
- Offline-capable PWA

### Module 2: Backend API
**Recommended Tech Stack**: Python FastAPI, PostgreSQL, Redis
- RESTful API with JWT authentication
- Session management (time-boxed check-ins)
- Check-in processing and validation
- Rate limiting and CORS
- Audit logging

### Module 3: Face Recognition & Risk Service
**Recommended Tech Stack**: Python, MediaPipe, OpenCV
- Liveness detection (blink, head pose)
- Face matching (with privacy controls)
- Risk scoring (signal fusion)
- Device attestation
- Anti-spoofing heuristics

### Module 4: Observability & Instructor Dashboard 
**Recommended Tech Stack**: Streamlit, Prometheus, Grafana
- Instructor web interface
- Real-time analytics
- Audit log explorer
- Metrics visualization
- CSV export for gradebook

---

## Getting Started

### Prerequisites
- Docker & Docker Compose
- Python 3.11+
- Node.js 18+

### Quick Start

```bash
# Navigate to project directory
cd student-starter

# Start infrastructure services (database, redis, prometheus)
docker-compose up -d postgres redis prometheus grafana

# Wait for services to be healthy
docker-compose ps

# Start developing your modules
# Each team member works on their assigned module
```

### Service URLs (when running)
- Frontend: http://localhost:3000
- Backend API: http://localhost:8000/docs
- Face Recognition: http://localhost:8001/docs
- Dashboard: http://localhost:8501
- Grafana: http://localhost:3001 (admin/admin)
- Prometheus: http://localhost:9090

---

## Running Tests

You have access to the public test suite (75% of your grade).

**IMPORTANT:** Tests send HTTP requests to your running services. Your services MUST be running before you run tests.

### Step 1: Install Test Dependencies

```bash
cd student-starter

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install test dependencies
pip install --upgrade pip
pip install -r requirements-test.txt
```

### Step 2: Start Your Services

```bash
# Build and start all your services
docker-compose up -d

# Wait for services to be healthy (about 30 seconds)
docker-compose ps

# Verify services are accessible
curl http://localhost:8000/health
curl http://localhost:8001/health
```

### Step 3: Run Tests

```bash
# Set test environment variables (optional - defaults to localhost)
export TEST_BACKEND_URL=http://localhost:8000
export TEST_FACE_URL=http://localhost:8001

# Run all public tests
python3 -m pytest tests/public/ -v

# Run specific test category
python3 -m pytest tests/public/test_api_functional.py -v
python3 -m pytest tests/public/test_security_basic.py -v
python3 -m pytest tests/public/test_privacy_basic.py -v
python3 -m pytest tests/public/test_face_recognition.py -v
python3 -m pytest tests/public/test_observability.py -v
python3 -m pytest tests/public/test_integration.py -v

# The scoring plugin shows a summary at the end:
# TOTAL SCORE: 90.0/90.0 (100.0%)
# LETTER GRADE: A
```

### Step 4: Stop Services

```bash
# Stop all services
docker-compose down

# Stop and remove volumes (clean slate)
docker-compose down -v
```

### Troubleshooting

**Tests skipping with "Backend service not running":**
```bash
docker-compose up -d
docker-compose ps  # Verify all services are "Up"
```

**Connection refused errors:**
```bash
export TEST_BACKEND_URL=http://localhost:8000
curl $TEST_BACKEND_URL/health
```

### Note on System Dependencies

Some packages require system-level dependencies:

- **face-recognition**: Requires `dlib` which needs `cmake` and C++ compiler
  - macOS: `brew install cmake`
  - Ubuntu: `sudo apt-get install cmake build-essential`

- **opencv-python**: Usually works out of the box, but may need:
  - Ubuntu: `sudo apt-get install libgl1-mesa-glx`

---

## Grading Breakdown

### Public Tests (90 points) - Available to you

| Test File | Points | Description |
|-----------|--------|-------------|
| test_api_functional.py | 26 | API endpoints, auth, CRUD operations |
| test_face_recognition.py | 15 | Face enrollment, matching, risk assessment |
| test_security_basic.py | 12 | JWT auth, input validation, rate limiting |
| test_privacy_basic.py | 8 | Consent, data minimization, retention |
| test_frontend_dashboard.py | 8 | Frontend/dashboard API contracts |
| test_observability.py | 12 | Stats, session management, export (bonus) |
| test_performance.py | 5 | Latency, concurrent users |
| test_integration.py | 4 | End-to-end check-in flow |

### Hidden Tests (40 points) - Revealed during grading

| Category | Points | Description |
|----------|--------|-------------|
| Advanced Security | 12 | GPS spoofing, replay attacks, VPN detection |
| Privacy Auditing | 8 | Database audit, encryption validation |
| Face Recognition Advanced | 10 | Advanced liveness, anti-spoofing |
| Liveness Bonus | 3 | Advanced liveness features |
| Stress Testing | 7 | Concurrent users, edge cases |

---

## Documentation

Please review these specifications carefully:

- **[API Specification](docs/API-SPECIFICATION.md)** - Complete endpoint documentation
- **[Database Schema](docs/recommended_design/DATABASE-SCHEMA.md)** - All table definitions

---

## Project Structure

```
student-starter/
├── frontend/          # PWA (your implementation)
├── backend/           # API (your implementation)
├── face-service/  # ML service (your implementation)
├── dashboard/     # Dashboard (your implementation)
├── tests/
│   ├── public/                # Public test suite (90 points)
│   └── scoring/               # Pytest scoring plugin
├── docs/
│   ├── API-SPECIFICATION.md
│   └── DATABASE-SCHEMA.md
└── docker-compose.yml
```

---

## Security Requirements

Your implementation must include:

1. **Authentication**
   - JWT tokens (HS256)
   - Bcrypt password hashing (cost >= 10)
   - Role-based access control

2. **Input Validation**
   - Sanitize all user input
   - Prevent SQL injection
   - Prevent XSS attacks

3. **Rate Limiting**
   - Protect against brute force
   - Use Redis for tracking

4. **Geofencing**
   - Validate GPS coordinates
   - Calculate distance to venue

---

## Required Admin Endpoints

Tests require these admin endpoints for test data setup. See [API Specification](docs/API-SPECIFICATION.md) for details.

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/admin/users/{id}/deactivate` | PATCH | Deactivate user (for testing inactive login) |
| `/api/v1/admin/users/{id}/activate` | PATCH | Reactivate user |
| `/api/v1/admin/users/bulk` | POST | Bulk create users (for stress tests) |
| `/api/v1/admin/sessions/{id}/status` | PATCH | Update session status |
| `/api/v1/admin/enrollments/` | POST | Create enrollment (admin bypass) |

**Note:** These endpoints require admin authentication and are used by the test suite to set up test scenarios.

---

## Privacy Requirements

Your implementation must:

1. **Never store raw face images** - Process in memory, store only hashes
2. **Track consent** - Camera and geolocation permissions
3. **Implement retention** - 30-day auto-deletion of records
4. **Create audit logs** - Immutable event trail

---

## Tips for Success

1. **Read the specifications thoroughly** before coding
2. **Run tests frequently** to catch issues early
3. **Communicate with your team** - modules must integrate
4. **Don't over-engineer** - focus on requirements
5. **Think about security** from the start
6. **Document your decisions** for the final report

---

## Common Pitfalls

Avoid these mistakes:
- Storing raw face images (automatic privacy test failure)
- Ignoring rate limiting (vulnerable to attacks)
- Missing geofence validation (easy to bypass)
- Poor error handling (crashes under load)
- Incorrect CORS configuration (frontend can't communicate)

---

## Questions?

- Review the API specification and database schema
- Run the public tests to understand requirements
- Check the skeleton code for implementation hints

Good luck with your capstone project!
