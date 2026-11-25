"""Worker role (task 4.1, RFC C2): claims jobs from the Postgres job table and runs them. Choices: DECISIONS.md D-017.

Claim = due rows FOR UPDATE SKIP LOCKED, then the farmer's advisory lock (pg_try_advisory_lock on user_key), held for
the whole run, so two jobs of one farmer never run at once in any worker; a busy farmer is skipped, never waited on.
A failing job goes back to 'queued' with run_at pushed out by an exponential backoff; after MAX_ATTEMPTS it is
dead-lettered (status 'dead', last_error kept). A crashed worker's job is re-claimed when its lease runs out (RFC §13).
"""
import logging
import os
import signal
import threading
from datetime import timedelta
from typing import NamedTuple

import psycopg

from app import handlers

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 5                # then dead-letter (RFC §13 "max 5", D-017)
LEASE = timedelta(minutes=5)    # 'running' past this = worker died → re-claimed; far above the 12 s turn budget (RFC §13)
WORKER_THREADS = 2              # RFC §14
POLL_S = 1.0                    # idle wait between empty claims
RECONNECT_S = 5.0

# Expired leases count as due. shortcut: looks at 20 due rows per claim, so >20 queued jobs of busy farmers can delay
# other farmers until one finishes; fine once 6.2 coalesces a farmer's messages into one turn.
CLAIM_SQL = """
SELECT id, kind, user_key, payload, attempts FROM job
WHERE (status = 'queued' AND run_at <= now()) OR (status = 'running' AND locked_until < now())
ORDER BY priority, run_at, id
LIMIT 20
FOR UPDATE SKIP LOCKED
"""


class Job(NamedTuple):
    id: int
    kind: str
    user_key: str | None
    payload: dict
    attempts: int  # including the current run


# kind -> handler(conn, job). A handler raises to fail the attempt (worker retries, then dead-letters). Added in task 5.1;
# `turn` is the temporary echo bot (task 6.2 replaces it), `status` is the forward-only delivery-receipt updater.
HANDLERS = {"turn": handlers.handle_turn, "status": handlers.handle_status}


def backoff(attempt: int) -> timedelta:
    """Delay after failed attempt n: 5 s, 10 s, 20 s, 40 s … capped at 10 min."""
    return timedelta(seconds=min(5 * 2 ** (attempt - 1), 600))


def claim(conn, lease: timedelta = LEASE) -> Job | None:
    """Mark one due job 'running' and take its farmer's lock; None if nothing is runnable now.
    The lock is session-level, so it outlives this transaction; if anything here raises, the caller must close conn."""
    with conn.transaction():
        for row in conn.execute(CLAIM_SQL).fetchall():
            job = Job(*row[:4], row[4] + 1)
            if job.user_key is None or conn.execute(
                "SELECT pg_try_advisory_lock(hashtextextended(%s, 0))", (job.user_key,)
            ).fetchone()[0]:
                conn.execute(
                    "UPDATE job SET status = 'running', attempts = %s, locked_until = now() + %s WHERE id = %s",
                    (job.attempts, lease, job.id),
                )
                return job
    return None


def run_one(conn, handlers=HANDLERS, max_attempts: int = MAX_ATTEMPTS, backoff=backoff, lease: timedelta = LEASE) -> Job | None:
    """Claim and run one job, record the outcome, release the farmer lock. Returns the job, or None if none was runnable.
    conn must be autocommit; handlers get the same connection."""
    job = claim(conn, lease)
    if job is None:
        return None
    try:
        handler = handlers.get(job.kind)
        error = None
        if handler is None:
            error = f"unknown job kind {job.kind!r}"  # retrying cannot help: dead-letter now
        elif job.attempts > max_attempts:
            error = "lease expired on the last attempt"  # the worker died during it
        else:
            try:
                handler(conn, job)
            except Exception as e:  # any handler failure is one failed attempt
                error = f"{type(e).__name__}: {e}"[:500]

        if error is None:
            conn.execute("UPDATE job SET status = 'done', locked_until = NULL, last_error = NULL WHERE id = %s", (job.id,))
        elif handler is not None and job.attempts < max_attempts:
            delay = backoff(job.attempts)
            conn.execute(
                "UPDATE job SET status = 'queued', run_at = now() + %s, locked_until = NULL, last_error = %s WHERE id = %s",
                (delay, error, job.id),
            )
            log.warning("job %s (%s): attempt %s failed; retry in %s", job.id, job.kind, job.attempts, delay)
        else:
            conn.execute("UPDATE job SET status = 'dead', locked_until = NULL, last_error = %s WHERE id = %s", (error, job.id))
            # no error text in logs (it can carry row data); alert + farmer fallback reply are task 17.1
            log.error("job %s (%s): dead-lettered after %s attempts", job.id, job.kind, job.attempts)
    finally:
        if job.user_key is not None:
            conn.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 0))", (job.user_key,))
    return job


def loop(stop: threading.Event):
    """One worker thread with its own connection. Any error: drop the connection (frees its farmer lock), wait, reconnect;
    a job it was running stays 'running' until its lease expires and is then re-claimed."""
    while not stop.is_set():
        try:
            with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True, connect_timeout=5) as conn:
                while not stop.is_set():
                    if run_one(conn) is None:
                        stop.wait(POLL_S)
        except Exception as e:  # keep the thread alive; type only, messages can carry row data
            log.error("worker: %s; reconnecting in %s s", type(e).__name__, RECONNECT_S)
            stop.wait(RECONNECT_S)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(threadName)s %(message)s")
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    threads = [threading.Thread(target=loop, args=(stop,), name=f"worker-{i}") for i in range(WORKER_THREADS)]
    for t in threads:
        t.start()
    print("worker ready", flush=True)
    try:
        while not stop.wait(1):
            pass
    except KeyboardInterrupt:
        stop.set()
    for t in threads:
        t.join()  # a running job finishes first; if killed instead, its lease expires and it is re-claimed
    print("worker stopped", flush=True)


if __name__ == "__main__":
    main()
