"""Web role: webhook gateway (task 2.2) and health check."""
import os

import psycopg
from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(title="MandiSaathi")


def db_ok() -> bool:
    try:
        with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=2) as conn:
            conn.execute("SELECT 1")
        return True
    except (KeyError, psycopg.Error):
        return False


@app.get("/health")
def health():
    if db_ok():
        return {"status": "ok", "db": "ok"}
    return JSONResponse({"status": "degraded", "db": "down"}, status_code=503)
