"""Apply app/migrations/NNN_*.sql in order, once each (task 2.3). Run: python -m app.migrate"""
import hashlib
import os
import sys
from pathlib import Path

import psycopg

MIGRATIONS = Path(__file__).parent / "migrations"
LOCK_ID = 2_003  # pg advisory lock key: one migrator at a time (web/worker/batch start together)


class MigrationError(RuntimeError):
    pass


def checksum(path: Path) -> str:
    # CRLF → LF so a Windows checkout and the VM's checkout hash the same
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def migrate(conninfo: str, migrations_dir: Path = MIGRATIONS) -> list[str]:
    """Apply pending migrations; return the versions applied. Raises MigrationError on a failed or edited migration."""
    files = sorted(migrations_dir.glob("[0-9][0-9][0-9]_*.sql"))
    applied_now = []
    with psycopg.connect(conninfo, autocommit=True) as conn:
        conn.execute("SELECT pg_advisory_lock(%s)", (LOCK_ID,))
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                " version text PRIMARY KEY, checksum text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())"
            )
            done = dict(conn.execute("SELECT version, checksum FROM schema_migrations").fetchall())
            for f in files:
                version, digest = f.stem, checksum(f)
                if version in done:
                    if done[version] != digest:
                        raise MigrationError(f"{f.name} changed after it was applied; add a new migration instead")
                    continue
                try:
                    with conn.transaction():
                        conn.execute(f.read_text(encoding="utf-8"))
                        conn.execute("INSERT INTO schema_migrations (version, checksum) VALUES (%s, %s)", (version, digest))
                except psycopg.Error as e:
                    raise MigrationError(f"{f.name} failed and was rolled back: {e}") from e
                applied_now.append(version)
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK_ID,))
    return applied_now


def main() -> int:
    try:
        applied = migrate(os.environ["DATABASE_URL"])
    except KeyError:
        print("migrate: DATABASE_URL is not set", file=sys.stderr)
        return 1
    except (MigrationError, psycopg.Error) as e:
        print(f"migrate: {e}", file=sys.stderr)
        return 1
    print(f"migrate: applied {applied}" if applied else "migrate: 0 pending")
    return 0


if __name__ == "__main__":
    sys.exit(main())
