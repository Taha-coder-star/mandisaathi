"""Web role: webhook gateway (task 2.2) and health check."""
from fastapi import FastAPI

app = FastAPI(title="MandiSaathi")


@app.get("/health")
def health():
    # task 2.1 adds the DB reachability check
    return {"status": "ok"}
