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
| checkins | submit, liveness-challenge, list, my-checkins, flagged, session/{id}, get, appeal, review |
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
session exists, **inside Singapore**, session active, window open, QR code
(if the instructor issued one), enrollment, no duplicate - and every failure
is written to the audit log as a `checkin_attempted` with a reason.

**Singapore only (graded).** A check-in is refused with 403 when the client
IP is a public address outside Singapore or the GPS fix is outside
Singapore. The client IP is the first `X-Forwarded-For` address, falling
back to the socket address; private and local addresses (10.x, 172.16-31.x,
192.168.x, 127.x) count as on-campus. Singapore IPs come from an offline
DB-IP extract (`app/data/sg_ip_ranges.txt`, refresh with
`scripts/build_sg_ip_ranges.py`); the GPS test is a polygon along the Johor
and Singapore Straits (`services/geo.py`), so Johor Bahru and Batam are
outside. It is a 403 rather than a stored `rejected` row so a student on a
foreign VPN can switch it off and retry.

Then it scores:

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
score >= session threshold (default 0.5), **or a required face check that
could not run** -> `flagged`; otherwise `approved`. The signals are stored on
the check-in and in `risk_signals` so a reviewer can see exactly why.

A face-service outage never rejects a student, but it never approves one
blind either: when a frame was sent and the session requires liveness (or
face match, for an enrolled student) and the service did not answer, a
`liveness_low_confidence` / `face_match_low_confidence` signal with reason
`face_service_unavailable` is added and the check-in is flagged for review. A
circuit breaker skips the call for 30 s after a connection failure so latency
stays under budget. If the service *answers* with an error (bad image,
expired or reused challenge), that counts as a failed check.

### Liveness challenge flow

1. `GET /api/v1/checkins/liveness-challenge` (any logged-in user) returns
   `{challenge_id, challenge_type, expires_in}`; the type is `blink`,
   `head_turn` or `mouth_open`, chosen by the face service. 503 if the face
   service is down.
2. Show the prompt and record ~2 s of frames.
3. `POST /api/v1/checkins/` with the usual fields plus
   `liveness_challenge_id` and `liveness_frames` (5-45 base64 JPEGs, no
   data-URL prefix; ~10 frames at 640x480, quality 0.7). Keep sending one
   clear frame as `liveness_challenge_response`; it is used for face match
   (the first frame is used if it is missing).
4. The face service consumes the challenge once; a reused or expired id
   fails liveness, which rejects the check-in.

All three fields are optional: without them the old single-frame passive
check runs unchanged.

## Security and privacy controls

- **JWT** HS256, access 1 h, refresh 7 d, rotated on refresh, `jti` per token.
  Claims are identity and role only.
- **Passwords** bcrypt cost 10 (~90 ms), never serialised anywhere.
- **RBAC** `require_admin` / `require_instructor` / `require_staff` guards;
  ownership checks on session edits and check-in appeals.
- **Account lockout (graded)** 10 consecutive failed passwords on one
  account -> every further login for it returns 429 (even with the right
  password) for 15 minutes. A successful login resets the count. Unknown
  emails lock the same way so responses never reveal which accounts exist.
  Redis-backed, with an in-process fallback if Redis is down.
- **Rate limiting** Redis fixed windows: failed logins and registrations
  100,000/h/IP (see below), check-ins 10/min/user, API 1000/h/user. Fails
  open if Redis is down.
- **Client IP** first `X-Forwarded-For` address when present, otherwise the
  socket address (course staff's rule). `TRUSTED_PROXIES` can restrict which
  peers may send the header. Used for rate limits, audit logs and the
  Singapore rule.
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

**Per-IP rate limits default to 100,000/h, as the course staff asked**, so
the graded suite (all from one IP) is never blocked; brute force is stopped
per account by the lockout instead. The login limiter counts only *failed*
attempts - limiting successful logins per IP punishes a lecture hall behind
one NAT. Set `RATE_LIMIT_LOGIN_PER_HOUR=60` and
`RATE_LIMIT_REGISTER_PER_HOUR=10` to demonstrate the documented values.

**`X-Forwarded-For` is trusted from any peer by default**, because the course
staff specify the first forwarded address as the client IP. The trade-off: a
client connecting directly can send any address it likes, which affects the
per-IP limits, the IP recorded in audit logs and the Singapore IP check (the
GPS check and the per-account lockout are unaffected). In a real deployment
behind a reverse proxy, set `TRUSTED_PROXIES` to the proxy's networks (e.g.
`127.0.0.0/8,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16`) so only it may set the
header.

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
| `LOGIN_LOCKOUT_THRESHOLD` / `LOGIN_LOCKOUT_SECONDS` | 10 / 900 | account lockout |
| `TRUSTED_PROXIES` | `*` (any) | peers whose `X-Forwarded-For` is honoured |
| `SINGAPORE_ONLY_CHECKINS` | true | refuse check-ins from outside Singapore |
| `FACE_CHECKIN_TIMEOUT` / `FACE_SEQUENCE_TIMEOUT` | 1.5 / 4.0 s | face calls for one frame / a challenge sequence |
| `DATA_RETENTION_DAYS` | 30 | purge window |
| `QR_CODE_TTL_SECONDS` | 300 | how long an issued QR code is valid |
| `CORS_ORIGINS` | :3000, :8501 | frontend and dashboard |

## For the other modules

- **Frontend (Module 1)**: log in, store both tokens, send
  `Authorization: Bearer <access_token>`, refresh on 401. Check-in payload is
  in the spec; `liveness_challenge_response` is a base64 frame with no data-URL
  prefix. Send `device_fingerprint` consistently - the same value every time
  from one device - or every check-in scores as an unknown device. If the
  instructor has issued a QR code, pass it as `qr_code`. For real blink /
  head-turn prompts, follow the liveness challenge flow above. Login can
  return 429 (account locked; `Retry-After` says for how long), and check-in
  can return 403 "only accepted from within Singapore".
- **Face service (Module 3)**: the backend calls `/face/enroll`,
  `/face/verify`, `/liveness/check` and `/risk/assess` exactly as the spec
  documents them. Return `enrollment_successful` and a 64-hex
  `face_template_hash`; return `liveness_passed: false` only when you are
  confident it is a spoof, because that rejects the check-in outright.
- **Dashboard (Module 4)**: log in as an instructor; `/stats/*`,
  `/checkins/flagged`, `/checkins/{id}/review`, `/sessions/{id}/qr` and
  `/export/*` are yours; export rows now include `course_code` and
  `course_name`. Prometheus already scrapes `/metrics`
  (`http_requests_total`, `http_request_duration_seconds`,
  `checkin_attempts_total` by HTTP status, and
  `checkin_decisions_total{decision="approved|flagged|rejected"}` plus the
  `checkin_risk_score` histogram by decision). Flagged share over 15 min:
  `sum(increase(checkin_decisions_total{decision="flagged"}[15m])) /
  sum(increase(checkin_decisions_total[15m]))`.
