# Dashboard audit checklist

## Scope and evidence

This audit compares the dashboard with `../docs/API-SPECIFICATION.md` and the
Module 4 requirements supplied in the task. The Module 4 lecture slides were
not found in the repository or Downloads, so slide-specific wording and any
requirements not listed in the task remain unverified. Dashboard tests use
mocked HTTP responses. The backend/API suite was also run against rebuilt local
containers; a browser smoke check reached the dashboard sign-in page, but no
authenticated browser workflow was performed.

`PASS` means implemented and verified by the stated evidence. `PARTIAL` means
implemented with a known limitation or without live integration verification.
`FAIL` means missing or broken. `BLOCKED` means an external dependency or
conflicting contract prevents verification.

## Part 1 and 5 — roles, scope, and actions

| Requirement | Status | Evidence / limitation |
|---|---|---|
| Cumulative student → TA → instructor permissions; admin gets all dashboard permissions | PASS | `app/rbac.py`; `tests/test_rbac.py` |
| Navigation and direct page entry fail closed for absent/invalid roles and forged page selections | PASS | `app/main.py`, `app/rbac.py`; role matrix and refresh/page-selection tests in `tests/test_rbac.py` |
| Student own history and devices; device rename/revoke actions are guarded | PASS | `app/views/student.py`, `app/api_client.py`; backend device routes enforce ownership |
| Student check-in submission | PARTIAL | Dashboard links to the existing student portal (`app/config.py`, `app/views/student.py`); submission remains in `../frontend/components/CheckinFlow.tsx` |
| Student appeal of an eligible own check-in | PASS | `app/views/student.py`, `app/api_client.py`; backend endpoint enforces owner, status, one-time, and seven-day checks |
| TA session check-in and flagged-review pages | PARTIAL | Explicit TA-course assignment table/routes and admin assignment UI are implemented in `../backend/app/models/course_ta.py`, `../backend/app/routers/courses.py`, and `app/views/courses.py`. Course-scope helpers and review authorization are unit tested; live API permission behavior is not verified. |
| Instructor course/session/roster/analytics scope in dashboard and API | PARTIAL | Dashboard filters in `app/access.py`; backend scope helpers protect sessions, check-ins, stats, rosters, reviews and exports. Unit tests cover course denial/assignment and export access, but no live API integration is available. |
| Instructor student details limited to selected course | PASS | `app/views/courses.py`; backend student stats filter to assigned/enrolled courses and reject cross-course reads |
| Admin access to dashboard pages, including user/course/device management and TA assignments | PARTIAL | Admin-only page includes account, course, device and TA assignment actions. API behavior is wrapper/unit-tested but not live-integrated. |
| Backend authorization for direct API access to scoped staff data | PARTIAL | Course/session/check-in/review/stats/enrollment/export paths now enforce roles and course scope. Open role-selectable self-registration and live route integration remain unresolved; frontend checks are not security boundaries. |

## Part 2 — observability requirements

| Requirement | Status | Evidence / limitation |
|---|---|---|
| Today's sessions and check-ins, approval rate, flagged queue | PASS | `app/views/overview.py`; API results are date-filtered |
| Attendance percentage | PASS (unit-tested) | Backend overview/session/course percentages now count only approved records over eligible enrollment slots; `tests/unit/test_course_authorization.py` verifies export attendance denominator. |
| Flagged versus approved counts/share | PASS | `app/views/overview.py`; missing or incomplete outcome counts are shown as unavailable |
| Average risk score and distribution | PARTIAL | `app/views/overview.py` and `app/views/courses.py`; displayed distributions/averages are sampled (latest up to 100 records), not full-population distributions |
| Check-ins per session and attendance trend | PASS | `app/views/courses.py`; bar and line charts use course statistics |
| Labels, semantic colors, zero-based count axes, bounded percentage/risk axes | PASS | `app/views/overview.py`, `app/views/courses.py`, `app/views/observability.py` |
| 30-second dashboard refresh | PASS | Overview and observability use `st_autorefresh(interval=30_000)` |
| High flagged-decision-rate alert at >30% over 15 minutes | PASS | `app/views/observability.py`, `dashboard/prometheus-alert-rules.yml`; UI query matches Prometheus alert expression |
| Loading, error, and empty states | PARTIAL | Present in major views; API response shapes and service outages lack live integration verification |
| Responsive horizontally scrollable tables | PASS | Full-width Streamlit dataframes; responsive overflow styling in `app/main.py` |
| Module 4 slide-by-slide compliance | BLOCKED | Lecture slides were not found; only requirements enumerated in the task were audited. |

## Part 3 — attendance exports

| Requirement | Status | Evidence / limitation |
|---|---|---|
| Course/session CSV and JSON download actions | PASS | `app/views/courses.py`, `app/views/sessions.py`, `app/views/_downloads.py`, `app/api_client.py` |
| Student ID/name/email, course, session, date, status, check-in timestamp, risk score | PASS | Export schema in `../backend/app/routers/export.py`; CSV and JSON include all required fields |
| CSV field quoting/escaping and UTF-8 output | PASS (unit-tested) | Backend `csv.DictWriter`, UTF-8 BOM, formula neutralization; test in `tests/unit/test_course_authorization.py`; dashboard byte pass-through test in `tests/test_p0_fixes.py` |
| JSON UTF-8/non-ASCII preservation | PASS | `app/views/_downloads.py` uses `ensure_ascii=False` and UTF-8 encoding |
| Export date filters from dashboard | PASS | Course page passes its selected UTC date range to CSV and JSON exports; client tests verify query parameters. |
| Spreadsheet formula neutralization for untrusted CSV text | PASS (unit-tested) | Backend neutralizes leading formula characters in string cells; `tests/unit/test_course_authorization.py` |
| Backend authorization of course/session exports | PARTIAL | Course and session scope enforced and unit-tested; no live auth integration test or deployment verification. |

## Part 4 — SAIV API integration

The dashboard API client is `app/api_client.py`. Protected calls pass the
authenticated token through the existing client; public endpoints such as
`GET /sessions/active` are intentionally unauthenticated by contract. HTTP
errors are returned to views, which generally display an error instead of
substituting mock data. No mock-data fallback was found in the audited views.

| Specification endpoint(s) | Status | Dashboard integration |
|---|---|---|
| `POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout`, `GET /users/me` | PARTIAL | Login/refresh/logout wrappers exist; role comes from authenticated session context. `GET /users/me` wrapper is not used as a role refresh. Public registration still accepts a requested role and needs a secure provisioning/bootstrap design. |
| `PUT /users/me`, `GET /users/`, `GET /users/{id}`, `PATCH /users/{id}` | PARTIAL | Admin user listing, role/status update, and creation via `app/views/administration.py` and `app/api_client.py`; self-profile editing and user detail UI are absent. |
| `GET /courses/`, `GET /courses/{id}` | PARTIAL | List/detail wrappers and paginated course loading are implemented; staff results are scoped. The catalog is public per the current API specification; live API tests passed, but the suite does not verify course-scoped staff detail access. |
| `POST /courses/`, `PATCH /courses/{id}`, `DELETE /courses/{id}` | PASS | Admin-only course create/update/deactivate UI in `app/views/administration.py`; backend routes are admin-only. |
| `GET /courses/{id}/tas`, `POST /courses/{id}/tas`, `DELETE /courses/{id}/tas/{ta_id}` | PARTIAL | Admin assignment UI/client and backend scope/role checks implemented; authorization helper behavior has unit-level tests, but live HTTP tests do not cover TA assignment isolation. |
| `GET /sessions/`, `GET /sessions/{id}`, `POST /sessions/`, `PATCH /sessions/{id}`, `DELETE /sessions/{id}` | PARTIAL | Session listing/management exists; backend course scope is enforced. Live suite ran, but does not cover cross-course session access for every role. |
| `GET /sessions/active` | PARTIAL | API-client wrapper exists; dashboard does not use it. The separate student portal handles check-in session discovery. |
| `GET /sessions/my-sessions` | PASS | Instructor/TA sessions are restricted to assigned courses; students receive sessions only for active enrollments. |
| Session QR endpoints | PARTIAL | Dashboard client and controls support QR create/clear; these routes are additional to the documented endpoint list. |
| `POST /checkins/` | PARTIAL | Submission is in the separate student portal (`../frontend/components/CheckinFlow.tsx`), not in the Streamlit dashboard. |
| `GET /checkins/`, `/my-checkins`, `/session/{id}`, `/flagged`, `/{id}`, `POST /{id}/review`, `POST /{id}/appeal` | PARTIAL | Dashboard client/views cover exploration, review, personal records and appeals. Backend course scoping and student ownership have unit tests; live suite does not verify cross-course role isolation for every route. |
| `GET /stats/overview`, `/stats/sessions/{id}`, `/stats/courses/{id}`, `/stats/students/{id}` | PARTIAL | Overview/session/course statistics integrated; student stats allows self or course-scoped instructor/admin. Attendance calculations and date ranges have unit tests; live suite does not cover all role/course isolation cases. |
| `POST /devices/register` | PARTIAL | Existing student portal registers devices (`../frontend/lib/device.ts`); not called from the dashboard. |
| `GET /devices/my-devices`, `PATCH /devices/{id}`, `DELETE /devices/{id}` | PASS | Student-owned device list, rename, and revoke; admin device trust controls are in the administration view. |
| `GET /enrollments/my-enrollments`, `GET /enrollments/course/{id}`, `POST /enrollments/`, `/bulk`, `DELETE /enrollments/{id}` | PARTIAL | Roster, bulk enrollment and drop are integrated. Student enrollment listing and single enrollment UI are absent; mutations are backend instructor/admin-only and course-scoped, with unit tests for permitted/forbidden enrollment. |
| `GET /audit/` and audit summary | PASS | Admin-only audit view supports filtering and pagination. |
| Course/session CSV and JSON exports | PARTIAL | Both formats and course export date filters are integrated. Backend scopes exports and calculates rates from approved check-ins; live API behavior is not verified. |
| Admin test endpoints and user/course/device management routes | PARTIAL | User/course/device administration and TA assignments are integrated; retention operations have no dashboard UI. |
| Pagination | PARTIAL | Session, check-in, flagged queue, audit, course, and admin user/course/device lists paginate. Personal check-ins/my-sessions use fixed limits; session check-in and roster endpoints return unpaginated data. |
| Error/response handling | PARTIAL | Most calls surface errors and validate response shapes. Dashboard tests use mocks; no live backend compatibility verified. |

### Specification discrepancies observed

- The backend exposes `instructor_id`/`instructor_name` on courses, contrary to
  the old note in the specification; the specification has been updated.
- The specification documents `/checkins/flagged` as an array, while the
  current backend returns a paginated `{items,total,limit,offset}` response;
  the dashboard follows the current backend response.
- Public course-catalog reads match the current API specification. Staff detail
  access is course-scoped; public catalog behavior has not been verified against
  a live deployed service.
- Public registration accepts a caller-selected role, including `admin`; the
  current API contract has no safe first-admin provisioning/bootstrap flow.
  This is a high-priority authorization blocker requiring an explicit
  deployment/bootstrap design, not a frontend workaround.

## Part 6 — security and dependencies

- Frontend RBAC is defense in depth, not backend authorization. A user can call
  API routes directly; backend row/course ownership checks are required.
- `../backend/app/services/authorization.py` enforces explicit instructor
  ownership and TA assignments for backend course-scoped operations.
- `../backend/app/models/course_ta.py` and admin-only assignment routes define
  the TA-course mapping; TA review checks the session's course assignment.
- Enrollment roster/mutations and analytics are instructor/admin-only;
  sessions, check-ins, reviews, and exports are scoped to assigned course IDs.
- `app/auth.py` and `app/views/review_queue.py` escape dynamic identity strings
  before inserting them into unsafe HTML. This protects dashboard-rendered
  labels only; it does not replace server-side input validation.
- CSV output uses UTF-8, CSV quoting, and spreadsheet formula-prefix
  neutralization; this is unit-tested.

## Part 7 — verification performed

- Dashboard pytest suite: **58 passed** (`python -m pytest -q`, from `dashboard`).
- Backend/API suite against rebuilt local containers: **102 passed, 1 skipped,
  1 failed** (`python -m pytest ..\tests -q`, from `backend`, with test URLs set
  to `127.0.0.1`). The failing test is
  `tests/public/test_face_recognition.py::TestFaceServiceHealth::test_root_endpoint_lists_endpoints`:
  the face-service index contains descriptive strings such as
  `POST /face/enroll - ...`, while that test asserts an exact bare path. This
  does not involve dashboard or backend authorization code.
- Tests cover cumulative permissions, invalid roles, navigation/page-selection
  behavior across all four roles, refresh role preservation, instructor course
  filtering, TA fail-closed behavior, session actions, API wrapper paths, export
  byte preservation, observability calculations, TA assignment, course-scoped
  exports, and enrollment route access.
- Python compilation and `git diff --check` passed after the latest code changes.
- Backend, dashboard, face-service, Prometheus, and Grafana health endpoints
  returned HTTP 200 after rebuild. The browser smoke check verified the
  dashboard sign-in screen and all four role names; it did not authenticate.
- No authenticated browser workflow or slide-by-slide Module 4 verification
  is claimed.
