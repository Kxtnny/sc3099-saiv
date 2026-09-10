"""
Clear accumulated test data from the development database.

What this can and cannot remove, and why:

* Attendance data - check-ins, risk signals, enrollments, sessions, devices,
  courses - is freely deletable, in that order (children before parents).
* Users are NOT deletable. Every user has audit rows referencing them, and
  audit rows are append-only, so the foreign key blocks the delete. This is
  the compliance guarantee working as designed. Use --anonymize to strip the
  personal data instead, which is the same path GDPR erasure takes.
* audit_logs is never touched. Database triggers reject UPDATE, DELETE and
  TRUNCATE on it.

For a genuinely blank database, drop the volume instead:

    docker compose down -v
    docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d postgres redis backend

Usage:

    python backend/scripts/cleanup_db.py                 # show what is there
    python backend/scripts/cleanup_db.py --attendance    # wipe attendance data
    python backend/scripts/cleanup_db.py --attendance --keep-demo
    python backend/scripts/cleanup_db.py --anonymize     # scrub test-user PII
"""

import argparse
import subprocess
import sys

CONTAINER = "saiv-postgres"
DB_USER = "saiv"
DB_NAME = "saiv"

# Children first: each table only references ones later in the list.
ATTENDANCE_TABLES = [
    "risk_signals",
    "checkins",
    "enrollments",
    "sessions",
    "devices",
    "courses",
]

ALL_TABLES = ATTENDANCE_TABLES + ["users", "audit_logs"]

# Accounts created by seed_demo.py, worth keeping across a cleanup.
DEMO_EMAIL_PATTERN = "%@demo.ntu"


def psql(sql: str) -> str:
    """Run SQL in the Postgres container and return stdout+stderr."""
    result = subprocess.run(
        ["docker", "exec", CONTAINER, "psql", "-U", DB_USER, "-d", DB_NAME, "-tAc", sql],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 and "ERROR" not in result.stderr:
        print(
            f"Could not reach Postgres in container '{CONTAINER}'.\n"
            "Is it running?  docker compose ps",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return (result.stdout + result.stderr).strip()


def counts() -> dict:
    rows = psql(
        " UNION ALL ".join(
            f"SELECT '{t}', count(*)::text FROM {t}" for t in ALL_TABLES
        )
    )
    out = {}
    for line in rows.splitlines():
        if "|" in line:
            name, value = line.split("|", 1)
            out[name] = int(value)
    return out


def show(title: str, data: dict) -> None:
    print(f"\n{title}")
    for table in ALL_TABLES:
        note = ""
        if table == "audit_logs":
            note = "  (append-only, never cleared)"
        elif table == "users":
            note = "  (cannot be deleted - audit rows reference them)"
        print(f"  {table:<14} {data.get(table, 0):>6}{note}")


def wipe_attendance(keep_demo: bool) -> None:
    """Delete attendance data, children before parents."""
    if keep_demo:
        # Keep the demo course and everything hanging off it.
        demo_course = psql("SELECT id FROM courses WHERE code = 'SC3099' LIMIT 1")
        if demo_course and "ERROR" not in demo_course:
            print(f"Keeping demo course SC3099 ({demo_course})")
            statements = [
                f"DELETE FROM risk_signals WHERE checkin_id IN (SELECT c.id FROM checkins c JOIN sessions s ON s.id = c.session_id WHERE s.course_id <> '{demo_course}')",
                f"DELETE FROM checkins WHERE session_id IN (SELECT id FROM sessions WHERE course_id <> '{demo_course}')",
                f"DELETE FROM enrollments WHERE course_id <> '{demo_course}'",
                f"DELETE FROM sessions WHERE course_id <> '{demo_course}'",
                f"DELETE FROM devices WHERE user_id NOT IN (SELECT id FROM users WHERE email LIKE '{DEMO_EMAIL_PATTERN}')",
                f"DELETE FROM courses WHERE id <> '{demo_course}'",
            ]
        else:
            print("No demo course found; wiping everything.")
            statements = [f"DELETE FROM {t}" for t in ATTENDANCE_TABLES]
    else:
        statements = [f"DELETE FROM {t}" for t in ATTENDANCE_TABLES]

    # One transaction: either the whole cleanup lands or none of it does.
    script = "BEGIN; " + "; ".join(statements) + "; COMMIT;"
    output = psql(script)
    if "ERROR" in output:
        print(f"Cleanup failed:\n{output}", file=sys.stderr)
        raise SystemExit(1)
    print("Attendance data cleared.")


def anonymize_users(keep_demo: bool) -> None:
    """
    Strip personal data from test accounts without deleting the rows.

    Mirrors what services/retention.py does for the 30-day policy: the row and
    its audit history survive, the person behind it does not.
    """
    keep_clause = f"AND email NOT LIKE '{DEMO_EMAIL_PATTERN}'" if keep_demo else ""
    output = psql(
        f"""
        UPDATE users SET
            email = 'deleted-' || id || '@anonymized.invalid',
            full_name = 'Deleted User',
            face_embedding_hash = NULL,
            face_enrolled = false,
            camera_consent = false,
            geolocation_consent = false,
            is_active = false,
            last_login_at = NULL,
            scheduled_deletion_at = NULL
        WHERE email NOT LIKE '%@anonymized.invalid' {keep_clause};
        """
    )
    if "ERROR" in output:
        print(f"Anonymize failed:\n{output}", file=sys.stderr)
        raise SystemExit(1)
    print(f"Users anonymized: {output.replace('UPDATE ', '')}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--attendance",
        action="store_true",
        help="delete check-ins, sessions, enrollments, devices and courses",
    )
    parser.add_argument(
        "--anonymize",
        action="store_true",
        help="strip personal data from user rows (they cannot be deleted)",
    )
    parser.add_argument(
        "--keep-demo",
        action="store_true",
        help="preserve the SC3099 course and @demo.ntu accounts from seed_demo.py",
    )
    args = parser.parse_args()

    before = counts()

    if not args.attendance and not args.anonymize:
        show("Current contents", before)
        print(
            "\nNothing deleted - this was a dry run. Options:\n"
            "  --attendance            clear check-ins, sessions, courses, devices\n"
            "  --anonymize             scrub personal data from user rows\n"
            "  --keep-demo             spare the seed_demo.py data\n"
            "\nFor a completely blank database (the only way to clear audit_logs):\n"
            "  docker compose down -v"
        )
        return 0

    show("Before", before)
    print()

    if args.attendance:
        wipe_attendance(args.keep_demo)
    if args.anonymize:
        anonymize_users(args.keep_demo)

    show("After", counts())
    print(
        "\naudit_logs is unchanged by design - it is the compliance record.\n"
        "Use 'docker compose down -v' if you need it gone."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
