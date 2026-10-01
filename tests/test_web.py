from datetime import datetime

import pytest

from app import create_app


@pytest.fixture()
def client(tmp_path):
    app = create_app({
        "TESTING": True,
        "DATABASE": str(tmp_path / "web.sqlite3"),
        "TIMEZONE": "Asia/Seoul",
        "ADMIN_USERNAME": "admin",
        "ADMIN_PASSWORD": "password",
        "SECRET_KEY": "test-only-secret-key",
    })
    return app.test_client()


def login(client):
    response = client.post("/admin/login", data={"username": "admin", "password": "password"})
    assert response.status_code == 302
    return response


def test_web_requires_login_and_login_sets_cookie(client):
    assert client.get("/admin").status_code == 302
    response = login(client)
    assert "admin_token=" in response.headers["Set-Cookie"]
    assert client.get("/admin").status_code == 200


def test_production_startup_requires_secret_key(tmp_path):
    with pytest.raises(RuntimeError, match="SECRET_KEY is required"):
        create_app({
            "DATABASE": str(tmp_path / "missing-secret.sqlite3"),
            "ADMIN_USERNAME": "admin",
            "ADMIN_PASSWORD": "password",
        })


def test_web_student_update_and_safe_delete(client):
    login(client)
    import sqlite3
    connection = sqlite3.connect(client.application.config["DATABASE"])
    connection.execute("INSERT INTO students(uid, grade, class_number) VALUES ('A1', 3, 2)")
    connection.commit()
    connection.close()
    response = client.post("/admin/students/A1/edit",
                           data={"uid": "A2", "grade": "4", "class": "1"})
    assert response.status_code == 302
    assert client.get("/admin").status_code == 200
    response = client.post("/admin/students/A2/delete", data={"confirm_uid": "wrong"})
    assert response.status_code == 302


def test_web_record_delete_requires_confirmation(client):
    login(client)
    db = client.application.config["DATABASE"]
    import sqlite3
    connection = sqlite3.connect(db)
    connection.execute("INSERT INTO students(uid, grade, class_number) VALUES ('A1', 3, 2)")
    connection.execute(
        "INSERT INTO meal_schedules(meal_date, meal_type, grade, class_number, starts_at, ends_at) "
        "VALUES (?, 'lunch', 3, 2, '11:00', '12:00')",
        (datetime.now().date().isoformat(),),
    )
    connection.execute("INSERT INTO meal_records(uid, schedule_id, served_at, source) VALUES ('A1', 1, 'now', 'scan')")
    connection.commit()
    connection.close()
    assert client.post("/admin/meals/1/delete", data={"confirm": "no"}).status_code == 302
    assert client.post("/admin/meals/1/delete", data={"confirm": "삭제"}).status_code == 302
