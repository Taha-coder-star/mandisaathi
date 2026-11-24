import os
import uuid

import psycopg
import pytest
from psycopg.conninfo import make_conninfo


@pytest.fixture
def db():
    """Throwaway database created through TEST_DATABASE_URL (a server we may create DBs on). Never point it at production."""
    admin_url = os.environ.get("TEST_DATABASE_URL")
    if not admin_url:
        if os.environ.get("CI"):
            raise RuntimeError("TEST_DATABASE_URL must be set in CI; DB tests may not skip there")
        pytest.skip("TEST_DATABASE_URL not set")
    name = f"mig_test_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    try:
        yield make_conninfo(admin_url, dbname=name)
    finally:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
