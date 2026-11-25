"""Task 4.1 DONE check: 2 jobs of one farmer never run concurrently; a failing job dead-letters after max attempts (RFC C2, §13).

Each test gets its own throwaway database (`db` fixture in conftest.py); every worker uses its own connection, as in production.
"""
import threading
import time
from collections import Counter
from datetime import timedelta

import psycopg
import pytest

from app import worker
from app.migrate import migrate


@pytest.fixture
def url(db):
    migrate(db)
    return db


def connect(url):
    return psycopg.connect(url, autocommit=True)


def add(c, kind="test", user_key=None, delay_s=0) -> int:
    return c.execute(
        "INSERT INTO job (kind, user_key, run_at) VALUES (%s, %s, now() + %s) RETURNING id",
        (kind, user_key, timedelta(seconds=delay_s)),
    ).fetchone()[0]


def state(c, job_id):
    """(status, attempts, last_error, seconds until run_at)"""
    s, a, e, d = c.execute(
        "SELECT status, attempts, last_error, extract(epoch FROM run_at - now()) FROM job WHERE id = %s", (job_id,)
    ).fetchone()
    return s, a, e, float(d)


def advisory_locks(c):
    return c.execute(
        "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory'"
        " AND database = (SELECT oid FROM pg_database WHERE datname = current_database())"
    ).fetchone()[0]


def ok(conn, job):
    pass


def test_two_jobs_of_one_farmer_never_run_concurrently(url):
    with connect(url) as c:
        f1, f2, g1 = add(c, user_key="US.F"), add(c, user_key="US.F"), add(c, user_key="US.G")
    f1_running, g1_ran, g1_seen_during_f1 = threading.Event(), threading.Event(), []

    def handler(conn, job):
        if job.id == f1:
            f1_running.set()
            g1_seen_during_f1.append(g1_ran.wait(10))  # hold farmer F until another farmer's job has run
        elif job.id == g1:
            g1_ran.set()

    handlers, first = {"test": handler}, []

    def worker_1():
        with connect(url) as c1:
            first.append(worker.run_one(c1, handlers))

    t = threading.Thread(target=worker_1)
    t.start()
    assert f1_running.wait(10)
    with connect(url) as c2:
        second = worker.run_one(c2, handlers)  # F is busy in worker 1: must skip f2 (not wait) and take g1
    t.join(10)
    assert not t.is_alive()
    assert first[0].id == f1 and second.id == g1
    assert g1_seen_during_f1 == [True]  # g1 ran while f1 was still running: other farmers are not blocked

    with connect(url) as c:
        assert worker.run_one(c, handlers).id == f2  # F is free again once f1 is done
        assert worker.run_one(c, handlers) is None
        assert [state(c, j)[:3] for j in (f1, f2, g1)] == [("done", 1, None)] * 3
        assert advisory_locks(c) == 0  # every farmer lock released


def test_concurrent_workers_serialise_each_farmer(url):
    with connect(url) as c:
        ids = [add(c, user_key=f"US.{i % 3}") for i in range(15)] + [add(c) for _ in range(3)]
    mu, inflight, peak, runs = threading.Lock(), Counter(), Counter(), Counter()

    def handler(conn, job):
        with mu:
            inflight[job.user_key] += 1
            peak[job.user_key] = max(peak[job.user_key], inflight[job.user_key])
            runs[job.id] += 1
        time.sleep(0.02)
        with mu:
            inflight[job.user_key] -= 1

    def drain():
        with connect(url) as c:
            while worker.run_one(c, {"test": handler}) is not None:
                pass  # None = nothing runnable; the thread holding the busy farmer keeps draining it

    threads = [threading.Thread(target=drain) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert runs == Counter(ids)  # every job ran exactly once: no two claimers got the same job
    assert {k: v for k, v in peak.items() if k is not None} == {"US.0": 1, "US.1": 1, "US.2": 1}
    with connect(url) as c:
        assert c.execute("SELECT count(*) FROM job WHERE status <> 'done'").fetchone()[0] == 0
        assert advisory_locks(c) == 0


def test_failing_job_retries_with_backoff_then_dead_letters(url):
    def boom(conn, job):
        raise RuntimeError("boom")

    handlers = {"boom": boom}
    with connect(url) as c:
        j = add(c, kind="boom", user_key="US.F")
        delays = []
        for attempt in range(1, worker.MAX_ATTEMPTS):
            assert worker.run_one(c, handlers).id == j
            status, attempts, error, delay = state(c, j)
            assert (status, attempts, error) == ("queued", attempt, "RuntimeError: boom")
            expected = worker.backoff(attempt).total_seconds()
            assert expected - 2 < delay <= expected
            delays.append(delay)
            assert worker.run_one(c, handlers) is None  # backing off: not due yet
            c.execute("UPDATE job SET run_at = now() WHERE id = %s", (j,))  # let the backoff elapse
        assert delays == sorted(delays) and len(set(delays)) == len(delays)  # each wait longer than the last

        assert worker.run_one(c, handlers).id == j
        assert state(c, j)[:3] == ("dead", worker.MAX_ATTEMPTS, "RuntimeError: boom")
        c.execute("UPDATE job SET run_at = now() - interval '1 day' WHERE id = %s", (j,))
        assert worker.run_one(c, handlers) is None  # a dead job is never claimed again
        assert advisory_locks(c) == 0


def test_delayed_job_waits_until_due(url):
    with connect(url) as c:
        j = add(c, delay_s=3600)
        assert worker.run_one(c, {"test": ok}) is None
        c.execute("UPDATE job SET run_at = now() - interval '1 second' WHERE id = %s", (j,))
        assert worker.run_one(c, {"test": ok}).id == j
        assert state(c, j)[:2] == ("done", 1)


def test_skip_locked_claimers_never_share_a_job(url):
    with connect(url) as a, connect(url) as b:
        j1, j2 = add(a), add(a)
        b.execute("SET lock_timeout = '2s'")  # a claim that waited on the row lock would fail here instead of hanging
        with a.transaction():
            a.execute("SELECT 1 FROM job WHERE id = %s FOR UPDATE", (j1,))  # another claimer is mid-claim on j1
            assert worker.claim(b).id == j2  # skipped j1, did not wait for it
        assert worker.claim(b).id == j1
        assert worker.claim(a) is None  # both are 'running' under a live lease


def test_unknown_kind_dead_letters_at_once_and_known_kinds_finish(url):
    with connect(url) as c:
        u, t, s = add(c, kind="nope"), add(c, kind="turn", user_key="US.F"), add(c, kind="status", user_key="US.F")
        def noop(conn, job):  # real turn/status handlers (5.1) need inbound_event rows; they have own tests
            pass

        while worker.run_one(c, {"turn": noop, "status": noop}) is not None:
            pass
        assert state(c, u)[:3] == ("dead", 1, "unknown job kind 'nope'")  # no retries: it can never succeed
        assert [state(c, j)[:3] for j in (t, s)] == [("done", 1, None)] * 2


def test_expired_lease_is_reclaimed_and_dead_letters_after_max(url):
    with connect(url) as c:
        a, b = add(c, user_key="US.F"), add(c, user_key="US.G")
        c.execute(
            "UPDATE job SET status = 'running', locked_until = now() - interval '1 second',"
            " attempts = CASE WHEN id = %s THEN 1 ELSE %s END",
            (a, worker.MAX_ATTEMPTS),
        )  # both workers died mid-job; b was on its last attempt
        ran = []
        while worker.run_one(c, {"test": lambda conn, job: ran.append(job.id)}) is not None:
            pass
        assert ran == [a]
        assert state(c, a)[:2] == ("done", 2)
        assert state(c, b)[:3] == ("dead", worker.MAX_ATTEMPTS + 1, "lease expired on the last attempt")
