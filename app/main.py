import os

from fastapi import FastAPI

app = FastAPI(title="devops-pipeline")

# Version injectee au build Docker (sha du commit) ; "dev" en local.
APP_VERSION = os.getenv("APP_VERSION", "dev")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/version")
def version():
    return {"version": APP_VERSION}
