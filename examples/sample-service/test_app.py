from app import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_health_endpoint_returns_200() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_root_returns_html() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_fractal_returns_valid_structure() -> None:
    response = client.get("/fractal")
    assert response.status_code == 200
    data = response.json()
    assert data["type"] == "julia"
    assert "points" in data
    assert len(data["points"]) == data["height"]
    assert len(data["points"][0]) == data["width"]


def test_fractal_respects_dimensions() -> None:
    response = client.get("/fractal?width=200&height=150")
    data = response.json()
    assert data["width"] == 200
    assert data["height"] == 150
    assert len(data["points"]) == 150
    assert len(data["points"][0]) == 200


def test_fractal_clamps_extreme_values() -> None:
    response = client.get("/fractal?width=2000&height=2000&iterations=100")
    data = response.json()
    assert data["width"] <= 800
    assert data["height"] <= 600


def test_tricorn_returns_valid_structure() -> None:
    response = client.get("/tricorn")
    assert response.status_code == 200
    data = response.json()
    assert data["type"] == "tricorn"
    assert "points" in data
    assert len(data["points"]) == data["height"]
    assert len(data["points"][0]) == data["width"]


def test_tricorn_respects_dimensions() -> None:
    response = client.get("/tricorn?width=200&height=150")
    data = response.json()
    assert data["width"] == 200
    assert data["height"] == 150
    assert len(data["points"]) == 150
    assert len(data["points"][0]) == 200


def test_tricorn_clamps_extreme_values() -> None:
    response = client.get("/tricorn?width=2000&height=2000&iterations=1000")
    data = response.json()
    assert data["width"] <= 800
    assert data["height"] <= 600
    assert data["parameters"]["max_iterations"] <= 100


def test_tricorn_accepts_bounds() -> None:
    response = client.get("/tricorn?xmin=-1&xmax=1&ymin=-1&ymax=1")
    assert response.status_code == 200
    data = response.json()
    assert data["parameters"]["xmin"] == -1.0
    assert data["parameters"]["xmax"] == 1.0
    assert data["parameters"]["ymin"] == -1.0
    assert data["parameters"]["ymax"] == 1.0
