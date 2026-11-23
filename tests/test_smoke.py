import importlib

from fastapi.testclient import TestClient

from app import web
from app.web import app
from mandi import batch


def test_health_db_up(monkeypatch):
    monkeypatch.setattr(web, "db_ok", lambda: True)
    r = TestClient(app).get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "db": "ok"}


def test_health_db_down(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)  # real db_ok: no URL → down, never a false 200
    r = TestClient(app).get("/health")
    assert r.status_code == 503
    assert r.json()["db"] == "down"


def test_batch_exits_zero():
    assert batch.main() == 0


def test_packages_import():
    for m in ["app.worker", "mandi.ingest", "mandi.features", "mandi.models", "mandi.decide"]:
        importlib.import_module(m)
