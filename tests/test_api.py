from datetime import datetime
import pytest
from app import create_app
from app.time_rules import meal_status


@pytest.fixture()
def client(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "test.sqlite3"),
                      "TIMEZONE": "Asia/Seoul", "ADMIN_USERNAME": "admin",
                      "ADMIN_PASSWORD": "correct horse battery staple",
                      "SECRET_KEY": "test-only-secret-key"})
    return app.test_client()


@pytest.fixture()
def auth_client(client):
    response = client.post("/api/auth/login", json={
        "username": "admin", "password": "correct horse battery staple"
    })
    assert response.status_code == 200
    client.environ_base["HTTP_AUTHORIZATION"] = f"Bearer {response.get_json()['token']}"
    return client


def setup_data(auth_client, start="00:00", end="23:59"):
    assert auth_client.post("/api/students", json={"uid": "ABC123", "grade": 3, "class": 2}).status_code == 201
    today = datetime.now().date().isoformat()
    assert auth_client.post("/api/schedules", json={"date": today, "meal_type": "lunch",
                                               "grade": 3, "class": 2,
                                               "starts_at": start, "ends_at": end}).status_code == 201


def test_time_validation():
    assert meal_status(datetime.strptime("10:00", "%H:%M"), "11:00", "12:00") == "before_meal"
    assert meal_status(datetime.strptime("11:30", "%H:%M"), "11:00", "12:00") == "approved"
    assert meal_status(datetime.strptime("12:00", "%H:%M"), "11:00", "12:00") == "after_meal"


def test_authentication_and_scan_approval_and_duplicate(client, auth_client):
    assert client.post("/api/students", json={"uid": "ABC123", "grade": 3, "class": 2}).status_code == 401
    setup_data(auth_client)
    assert auth_client.post("/api/meal/scan", json={"uid": "ABC123"}).status_code == 201
    response = auth_client.post("/api/meal/scan", json={"uid": "ABC123"})
    assert response.status_code == 409 and response.get_json()["code"] == "duplicate_same_day"


def test_scan_unregistered(auth_client):
    response = auth_client.post("/api/meal/scan", json={"uid": "NOPE"})
    assert response.status_code == 404 and response.get_json()["code"] == "unregistered_card"


def test_scan_before_and_after_meal(auth_client):
    setup_data(auth_client, start="23:00", end="23:30")
    response = auth_client.post("/api/meal/scan", json={"uid": "ABC123"})
    assert response.status_code == 403
    assert response.get_json()["code"] == "before_meal_time"


def test_login_failure_expiry_and_logout(client):
    assert client.post("/api/auth/login", json={"username": "admin", "password": "wrong"}).status_code == 401
    login = client.post("/api/auth/login", json={
        "username": "admin", "password": "correct horse battery staple"
    })
    token = login.get_json()["token"]
    client.environ_base["HTTP_AUTHORIZATION"] = f"Bearer {token}"
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/students").status_code == 401


def test_expired_token_is_rejected(client):
    login = client.post("/api/auth/login", json={
        "username": "admin", "password": "correct horse battery staple"
    })
    token = login.get_json()["token"]
    client.application.config["SESSION_TTL_SECONDS"] = 0
    expired_login = client.post("/api/auth/login", json={
        "username": "admin", "password": "correct horse battery staple"
    })
    client.environ_base["HTTP_AUTHORIZATION"] = f"Bearer {expired_login.get_json()['token']}"
    response = client.get("/api/students")
    assert response.status_code == 401
