from fastapi import FastAPI

app = FastAPI(title="devops-pipeline")


@app.get("/health")
def health():
    return {"status": "ok"}
