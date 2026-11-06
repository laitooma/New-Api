from fastapi import FastAPI

app = FastAPI(title="New-Api")


@app.get("/health")
def health():
    return {"status": "ok"}
