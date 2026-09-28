from datetime import datetime
import pytest
from app import create_app
from app.time_rules import meal_status


@pytest.fixture()
def client(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "test.sqlite3"),
                      "TIMEZONE": "Asia/Seoul"})
    return app.test_client()


def setup_data(client, start="00:00", end="23:59"):
    assert client.post("/api/students", json={"uid": "ABC123", "grade": 3, "class": 2}).status_code == 201
    today = datetime.now().date().isoformat()
    assert client.post("/api/schedules", json={"date": today, "meal_type": "lunch",
                                               "grade": 3, "class": 2,
                                               "starts_at": start, "ends_at": end}).status_code == 201


def test_time_validation():
    assert meal_status(datetime.strptime("10:00", "%H:%M"), "11:00", "12:00") == "before_meal"
    assert meal_status(datetime.strptime("11:30", "%H:%M"), "11:00", "12:00") == "approved"
    assert meal_status(datetime.strptime("12:00", "%H:%M"), "11:00", "12:00") == "after_meal"


def test_scan_approval_and_duplicate(client):
    setup_data(client)
    assert client.post("/api/meal/scan", json={"uid": "ABC123"}).status_code == 201
    response = client.post("/api/meal/scan", json={"uid": "ABC123"})
    assert response.status_code == 409 and response.get_json()["code"] == "duplicate_same_day"


def test_scan_unregistered(client):
    response = client.post("/api/meal/scan", json={"uid": "NOPE"})
    assert response.status_code == 404 and response.get_json()["code"] == "unregistered_card"


def test_scan_before_and_after_meal(client):
    setup_data(client, start="23:00", end="23:30")
    response = client.post("/api/meal/scan", json={"uid": "ABC123"})
    assert response.status_code == 403
    assert response.get_json()["code"] == "before_meal_time"
