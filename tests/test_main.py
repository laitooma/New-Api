from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_ok():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_unknown_route_returns_404():
    response = client.get("/bonjour")
    assert response.status_code == 404


def test_version_returns_dev_by_default():
    response = client.get("/version")
    assert response.status_code == 200
    assert response.json() == {"version": "dev"}
