import importlib

from fastapi.testclient import TestClient

from app.web import app
from mandi import batch


def test_health():
    r = TestClient(app).get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_batch_exits_zero():
    assert batch.main() == 0


def test_packages_import():
    for m in ["app.worker", "mandi.ingest", "mandi.features", "mandi.models", "mandi.decide"]:
        importlib.import_module(m)
