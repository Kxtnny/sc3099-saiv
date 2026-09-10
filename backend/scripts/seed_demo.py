"""
Seed a small, predictable dataset for demos and manual testing.

Everything is created through the public HTTP API - the same path a real
client takes - so passwords get hashed, input gets validated and the actions
land in the audit log. Nothing is inserted straight into Postgres.

Safe to run repeatedly: accounts that already exist are reused rather than
duplicated.

    python backend/scripts/seed_demo.py
    python backend/scripts/seed_demo.py --url http://localhost:8000
    python backend/scripts/seed_demo.py --students 30   # bigger class
"""

import argparse
import sys
from datetime import datetime, timedelta, timezone

import httpx

PASSWORD = "demopass123"
COURSE_CODE = "SC3099"

# NTU LT26, where the labs actually run.
VENUE = {
    "venue_name": "NTU LT26",
    "venue_latitude": 1.3483,
    "venue_longitude": 103.6831,
    "geofence_radius_meters": 100.0,
}


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso(dt):
    return dt.isoformat() + "Z"


class Seeder:
    def __init__(self, base_url: str):
        self.api = base_url.rstrip("/") + "/api/v1"
        self.http = httpx.Client(timeout=60.0)

    def close(self):
        self.http.close()

    # -- helpers ----------------------------------------------------------
    def account(self, email: str, full_name: str, role: str) -> dict:
        """Register the account if it is new, then log in either way."""
        created = self.http.post(
            self.api + "/auth/register",
            json={
                "email": email,
                "password": PASSWORD,
                "full_name": full_name,
                "role": role,
            },
        )
        if created.status_code not in (201, 400):
            raise SystemExit(
                f"Could not register {email}: {created.status_code} {created.text[:200]}"
            )

        login = self.http.post(
            self.api + "/auth/login", json={"email": email, "password": PASSWORD}
        )
        if login.status_code != 200:
            raise SystemExit(
                f"Could not log in as {email}: {login.status_code} {login.text[:200]}\n"
                f"If this account predates the script, its password differs - "
                f"pick another email or reset the database."
            )

        body = login.json()
        return {
            "id": body["user"]["id"],
            "email": email,
            "role": role,
            "headers": {"Authorization": f"Bearer {body['access_token']}"},
            "is_new": created.status_code == 201,
        }

    def course(self, admin: dict, instructor: dict) -> dict:
        existing = self.http.get(
            self.api + "/courses/", params={"limit": 100}
        ).json()["items"]
        for row in existing:
            if row["code"] == COURSE_CODE:
                return row

        created = self.http.post(
            self.api + "/courses/",
            headers=admin["headers"],
            json={
                "code": COURSE_CODE,
                "name": "Capstone Project",
                "semester": "AY2024-25 Sem 1",
                "instructor_id": instructor["id"],
                "risk_threshold": 0.5,
                **VENUE,
            },
        )
        if created.status_code != 201:
            raise SystemExit(f"Course creation failed: {created.text[:200]}")
        return created.json()

    def enroll(self, admin: dict, student_id: str, course_id: str) -> None:
        # 400 means already enrolled, which is fine on a re-run.
        self.http.post(
            self.api + "/admin/enrollments/",
            headers=admin["headers"],
            json={"student_id": student_id, "course_id": course_id},
        )

    def session(self, instructor: dict, admin: dict, course_id: str) -> dict:
        now = utcnow()
        created = self.http.post(
            self.api + "/sessions/",
            headers=instructor["headers"],
            json={
                "course_id": course_id,
                "name": f"Demo Lecture {now:%d %b %H:%M}",
                "session_type": "lecture",
                "scheduled_start": iso(now + timedelta(minutes=5)),
                "scheduled_end": iso(now + timedelta(hours=2)),
                # Window already open, so you can check in immediately.
                "checkin_opens_at": iso(now - timedelta(minutes=10)),
                "checkin_closes_at": iso(now + timedelta(hours=3)),
                "require_liveness_check": False,
                "risk_threshold": 0.5,
                **VENUE,
            },
        )
        if created.status_code != 201:
            raise SystemExit(f"Session creation failed: {created.text[:200]}")

        session = created.json()
        # Check-in only works once the session is active.
        self.http.patch(
            f"{self.api}/admin/sessions/{session['id']}/status",
            headers=admin["headers"],
            json={"status": "active"},
        )
        return session

    def checkin(self, student: dict, session_id: str, lat: float, lon: float) -> dict:
        r = self.http.post(
            self.api + "/checkins/",
            headers=student["headers"],
            json={
                "session_id": session_id,
                "latitude": lat,
                "longitude": lon,
                "location_accuracy_meters": 10.0,
                "device_fingerprint": f"demo-device-{student['email']}",
            },
        )
        return r.json() if r.status_code == 201 else {"status": f"skipped ({r.status_code})"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--students", type=int, default=5)
    args = parser.parse_args()

    seeder = Seeder(args.url)
    try:
        health = seeder.http.get(args.url.rstrip("/") + "/health")
        if health.status_code != 200:
            print(f"Backend is not healthy: {health.text[:200]}", file=sys.stderr)
            return 1
    except httpx.ConnectError:
        print(
            f"Backend not reachable at {args.url}\n"
            "Start it: docker compose -f docker-compose.yml -f docker-compose.dev.yml "
            "up -d postgres redis backend",
            file=sys.stderr,
        )
        return 1

    print(f"Seeding {args.url} ...\n")

    admin = seeder.account("admin@demo.ntu", "Demo Admin", "admin")
    instructor = seeder.account("instructor@demo.ntu", "Dr Demo Instructor", "instructor")
    ta = seeder.account("ta@demo.ntu", "Demo TA", "ta")
    students = [
        seeder.account(f"student{i}@demo.ntu", f"Demo Student {i}", "student")
        for i in range(1, args.students + 1)
    ]

    course = seeder.course(admin, instructor)
    for student in students:
        seeder.enroll(admin, student["id"], course["id"])

    session = seeder.session(instructor, admin, course["id"])

    # A spread of outcomes so the dashboard has something to show:
    # most students present, one just outside the geofence (flagged),
    # one left absent.
    outcomes = []
    for student in students[:-1]:
        if student is students[-2] and len(students) > 2:
            lat, lon, label = 1.3496, 103.6831, "outside geofence"
        else:
            lat, lon, label = 1.3483, 103.6831, "at venue"
        result = seeder.checkin(student, session["id"], lat, lon)
        outcomes.append((student["email"], label, result.get("status"), result.get("risk_score")))

    print("Accounts (password for all: " + PASSWORD + ")")
    for who in [admin, instructor, ta, *students]:
        tag = "new" if who["is_new"] else "existing"
        print(f"  {who['email']:<28} {who['role']:<11} ({tag})")

    print(f"\nCourse   {course['code']} - {course['name']}  [{course['id']}]")
    print(f"Session  {session['name']}  [{session['id']}]")
    print(f"         active, check-in open for ~3 hours, venue {VENUE['venue_name']}")

    print("\nCheck-ins created")
    for email, label, status, risk in outcomes:
        print(f"  {email:<28} {label:<18} -> {status} (risk {risk})")
    if students:
        print(f"  {students[-1]['email']:<28} {'no check-in':<18} -> absent")

    print(
        "\nTry it:\n"
        f"  Docs      {args.url}/docs   (Authorize with a token from /auth/login)\n"
        f"  Dashboard log in as instructor@demo.ntu\n"
        f"  Stats     GET /api/v1/stats/sessions/{session['id']}\n"
        f"  Flagged   GET /api/v1/checkins/flagged\n"
        f"  Export    GET /api/v1/export/session/{session['id']}?format=csv"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    finally:
        pass
