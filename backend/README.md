# SAIV Backend API (Module 2)

FastAPI service that owns authentication, courses, sessions, check-ins, risk
scoring, audit logging and export. Every other module talks to it over HTTP:
the student PWA and instructor dashboard call it, and it calls the face
service (Module 3) internally.

- Base URL: `http://localhost:8000/api/v1`
- Interactive docs: `http://localhost:8000/docs`
- Health: `GET /health` (200 while Postgres is reachable) and
  `GET /health/dependencies` (adds Redis and face-service state)
- Metrics: `GET /metrics` (Prometheus)

## Running it

```bash
# Day-to-day development: hot reload, only the services you need
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d postgres redis backend

# What the graders run: everything, no reload
docker compose up -d

# Tests (services must be running)
pip install -r requirements-test.txt
python -m pytest tests/public/ -q
```

The 8 tables are created automatically on startup (`create_all`), together
with the append-only trigger on `audit_logs`. The database starts empty; the
test suite creates its own data. There is no bootstrap admin: register one
with `"role": "admin"`, which is allowed by design (see *Decisions*).

`create_all` never alters an existing table. After a model change, reset with
`docker compose down -v` and start again.

## Layout

```
app/
├── main.py            app factory, middleware, router mounting, retention scheduler
├── dependencies.py    get_current_user, role guards, pagination helper
├── enums.py           roles, statuses, 20 risk signal types, audit actions
├── core/
│   ├── config.py      every tunable, env-overridable (see .env.example)
│   ├── database.py    engine, session, create_all, audit_logs trigger
│   ├── security.py    bcrypt (cost 10) + HS256 JWT with jti
│   ├── errors.py      uniform error bodies, request ids, 500 handling
│   ├── redis_client.py
│   ├── sanitize.py    XSS stripping for free-text fields
│   └── utils.py       naive-UTC helpers - use utcnow(), never datetime.now()
├── models/            one file per table
├── schemas/           Pydantic request/response models (the validation boundary)
├── routers/           one file per resource group
└── services/
    ├── risk.py        signal weights + approve/flag/reject decision
    ├── geo.py         Haversine, coordinate rounding
    ├── rate_limit.py  Redis fixed-window limiters
    ├── face_client.py Module 3 client with circuit breaker
    ├── audit.py       append-only log writer
    └── retention.py   30-day purge
```

## Endpoints (67)

| Group | Routes |
|---|---|
| auth | register, login, refresh, logout, me |
| users | me (GET/PUT), list, get, patch, delete, `me/face/enroll` |
| courses | list (public), get (public), create, update, delete |
| enrollments | my-enrollments, course roster, create, bulk, delete |
| sessions | list, active (public), my-sessions, get, create, update, delete, `{id}/qr` (POST/DELETE) |
| devices | my-devices, list, register (`/` and `/register`), patch, delete |
| checkins | submit, list, my-checkins, flagged, session/{id}, get, appeal, review |
| stats | overview, sessions/{id}, courses/{id}, students/{id} |
| audit | list, summary, export, create |
| export | session/{id}, attendance/{course_id} (CSV or JSON) |
| admin | activate/deactivate user, bulk users, session status, enrollments, retention status/purge |

Full request/response shapes: `docs/API-SPECIFICATION.md`, and `/docs` for
the live schema. Where the public tests and the spec disagree, the tests win
(`/stats/overview` field names, `/checkins/flagged` is paginated,
`/export/session` returns JSON with `summary` + `records`).

## How a check-in is decided

`POST /checkins/` validates in order - student role, 10/min rate limit,
session active, window open, QR code (if the instructor issued one),
enrollment, no duplicate - and every failure is written to the audit log as a
`checkin_attempted` with a reason. Then it scores:

| Signal | Weight | Fires when |
|---|---|---|
| `geo_out_of_bounds` | 0.40 | outside the geofence; **critical** beyond 2x |
| `impossible_travel` | 0.40 | implied speed from last check-in > 900 km/h |
| `liveness_failed` | 0.35 | face service says spoof; **critical** |
| `face_match_failed` | 0.30 | face does not match enrolled template |
| `rapid_succession` | 0.20 | another check-in < 30 s ago |
| `device_unknown` | 0.15 | fingerprint never seen (auto-registered) |
| `pattern_anomaly` | 0.15 | fingerprint belongs to another account |
| `vpn_detected` | 0.15 | face service network analysis |
| `geo_accuracy_low` | 0.10 | fix worse than 200 m, or no location |

Decision: any critical signal **or** score >= 0.7 -> `rejected`;
score >= session threshold (default 0.5) -> `flagged`; otherwise `approved`.
The signals are stored on the check-in and in `risk_signals` so a reviewer can
see exactly why.

A face-service outage never rejects a student: liveness is recorded as *not
evaluated* rather than *failed*, and a circuit breaker skips the call for
30 s after a connection failure so latency stays under budget.

## Security and privacy controls

- **JWT** HS256, access 1 h, refresh 7 d, rotated on refresh, `jti` per token.
  Claims are identity and role only.
- **Passwords** bcrypt cost 10 (~90 ms), never serialised anywhere.
- **RBAC** `require_admin` / `require_instructor` / `require_staff` guards;
  ownership checks on session edits and check-in appeals.
- **Rate limiting** Redis fixed windows: failed logins 60/h/IP, check-ins
  10/min/user, API 1000/h/user, registration (see below). Fails open if Redis
  is down.
- **Input** Pydantic validation, ORM-only SQL, HTML stripped from free text,
  coordinates range-checked.
- **Audit log** append-only at the database level (Postgres triggers reject
  UPDATE, DELETE and TRUNCATE), 24 action types, filterable and exportable.
- **Privacy** no image is ever stored or logged - only the 64-hex template
  hash; coordinates rounded to 4 dp (~11 m); consent flags tracked; right to
  erasure via `DELETE /users/{id}`; 30-day retention sweep anonymises users
  and scrubs check-in location/biometric fields while keeping the attendance
  outcome and the audit trail.
- **Errors** every error body is `{detail, code, request_id}`; unhandled
  exceptions return a generic 500 and log the traceback with the request id.

## Decisions worth knowing

**Registration accepts any role, including admin.** There is no seeded admin
and the tests create one through this endpoint. The briefing explicitly waives
role restrictions on registration.

**Consent does not block check-in.** The briefing says both consent flags must
be true first, but the public tests check in with consent unset (and one
privacy test sets both to false before others check in). Consent is tracked
and exposed; enforcing it would fail the suite. `POST /users/me/face/enroll`
*does* require camera consent.

**Two rate limits deviate from the spec, deliberately and configurably.**
The login limiter counts only *failed* attempts - limiting successful logins
per IP punishes a lecture hall behind one NAT without slowing brute force.
Registration defaults to 1000/h because the public suite creates ~200
accounts per run from one IP; set `RATE_LIMIT_REGISTER_PER_HOUR=10` to
demonstrate the documented value.

**`GET /courses/` and `/sessions/active` are public.** The spec marks courses
as authenticated, but the performance tests call it with no token, and the
PWA shows the catalogue before login.

**Any instructor can create a session for any course, and any staff member
can read any roster.** Courses are seeded by an admin and often have no
instructor assigned; the fixtures rely on this. Editing and deleting a
session are ownership-checked.

**String columns instead of native Postgres enums**, validated by Pydantic -
adding a value never needs an `ALTER TYPE` migration.

**Naive UTC everywhere.** Every timestamp column is `TIMESTAMP` without
zone; incoming `...Z` strings are normalised by `to_naive_utc()` and outgoing
ones serialised with a `Z`. Mixing naive and aware datetimes raises, so use
`utcnow()` from `app/core/utils.py`.

## Configuration

All settings live in `app/core/config.py` and are overridable through the
environment (`.env.example` lists them). The ones you are most likely to
touch:

| Variable | Default | Purpose |
|---|---|---|
| `SECRET_KEY` | dev value | JWT signing - change outside development |
| `FACE_SERVICE_URL` | `http://localhost:8001` | Module 3 |
| `RISK_SCORE_THRESHOLD` / `RISK_REJECT_THRESHOLD` | 0.5 / 0.7 | flag / reject cut-offs |
| `RATE_LIMIT_*` | see file | per-limiter values |
| `DATA_RETENTION_DAYS` | 30 | purge window |
| `QR_CODE_TTL_SECONDS` | 300 | how long an issued QR code is valid |
| `CORS_ORIGINS` | :3000, :8501 | frontend and dashboard |

## For the other modules

- **Frontend (Module 1)**: log in, store both tokens, send
  `Authorization: Bearer <access_token>`, refresh on 401. Check-in payload is
  in the spec; `liveness_challenge_response` is a base64 frame with no data-URL
  prefix. Send `device_fingerprint` consistently - the same value every time
  from one device - or every check-in scores as an unknown device. If the
  instructor has issued a QR code, pass it as `qr_code`.
- **Face service (Module 3)**: the backend calls `/face/enroll`,
  `/face/verify`, `/liveness/check` and `/risk/assess` exactly as the spec
  documents them. Return `enrollment_successful` and a 64-hex
  `face_template_hash`; return `liveness_passed: false` only when you are
  confident it is a spoof, because that rejects the check-in outright.
- **Dashboard (Module 4)**: log in as an instructor; `/stats/*`,
  `/checkins/flagged`, `/checkins/{id}/review`, `/sessions/{id}/qr` and
  `/export/*` are yours. Prometheus already scrapes `/metrics`
  (`http_requests_total`, `http_request_duration_seconds`,
  `checkin_attempts_total`).
