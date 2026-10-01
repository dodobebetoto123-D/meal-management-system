from datetime import datetime, timedelta, timezone
import hashlib
import secrets
import sqlite3
from functools import wraps
from flask import Blueprint, current_app, g, jsonify, request
from werkzeug.security import check_password_hash

from .db import get_db
from .time_rules import meal_status, parse_hhmm
from . import configured_timezone

api = Blueprint("api", __name__)


def error(code, message, status=400):
    return jsonify({"code": code, "message": message}), status


def json_body():
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else None


def _token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def require_auth(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return error("authentication_required", "Bearer token is required", 401)
        token = header[7:].strip()
        if not token:
            return error("authentication_required", "Bearer token is required", 401)
        now = datetime.now(timezone.utc)
        db = get_db()
        row = db.execute(
            """SELECT a.id, a.username, s.id AS session_id, s.expires_at
               FROM admin_sessions s JOIN admins a ON a.id=s.admin_id
               WHERE s.token_hash=?""",
            (_token_hash(token),),
        ).fetchone()
        if not row:
            return error("authentication_required", "Invalid or expired token", 401)
        try:
            expires_at = datetime.fromisoformat(row["expires_at"])
        except ValueError:
            expires_at = datetime.min.replace(tzinfo=timezone.utc)
        if expires_at <= now:
            db.execute("DELETE FROM admin_sessions WHERE id=?", (row["session_id"],))
            db.commit()
            return error("authentication_required", "Invalid or expired token", 401)
        g.admin = row
        return view(*args, **kwargs)
    return wrapped


@api.post("/auth/login")
def login():
    body = json_body()
    username = body.get("username") if body else None
    password = body.get("password") if body else None
    if not isinstance(username, str) or not isinstance(password, str):
        return error("invalid_request", "username and password are required")
    admin = get_db().execute(
        "SELECT id, username, password_hash FROM admins WHERE username=?", (username,)
    ).fetchone()
    if not admin or not check_password_hash(admin["password_hash"], password):
        return error("invalid_credentials", "Invalid username or password", 401)
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=current_app.config["SESSION_TTL_SECONDS"]
    )
    db = get_db()
    db.execute(
        "INSERT INTO admin_sessions(admin_id, token_hash, expires_at) VALUES (?, ?, ?)",
        (admin["id"], _token_hash(token), expires_at.isoformat()),
    )
    db.commit()
    return jsonify({"token": token, "expires_at": expires_at.isoformat(), "username": admin["username"]})


@api.post("/auth/logout")
@require_auth
def logout():
    header = request.headers["Authorization"]
    get_db().execute("DELETE FROM admin_sessions WHERE token_hash=?", (_token_hash(header[7:].strip()),))
    get_db().commit()
    return jsonify({"status": "ok"})


@api.get("/health")
def health():
    return jsonify({"status": "ok"})


@api.get("/students")
@require_auth
def students():
    rows = get_db().execute(
        "SELECT uid, grade, class_number FROM students ORDER BY grade, class_number, uid"
    ).fetchall()
    return jsonify([dict(row) for row in rows])


@api.post("/students")
@require_auth
def create_student():
    body = json_body()
    if not body or not isinstance(body.get("uid"), str) or not body["uid"].strip():
        return error("invalid_request", "uid is required")
    try:
        grade, class_number = int(body["grade"]), int(body["class"])
        if not 1 <= grade <= 12 or class_number <= 0:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return error("invalid_request", "grade and class must be positive integers (grade 1-12)")
    db = get_db()
    try:
        db.execute("INSERT INTO students(uid, grade, class_number) VALUES (?, ?, ?)",
                   (body["uid"].strip(), grade, class_number))
        db.commit()
    except sqlite3.IntegrityError:
        return error("duplicate_student", "uid is already registered", 409)
    return jsonify({"uid": body["uid"].strip(), "grade": grade, "class": class_number}), 201


@api.get("/schedules")
@require_auth
def schedules():
    date = request.args.get("date")
    query = """SELECT id, meal_date, meal_type, grade, class_number,
                      starts_at, ends_at
               FROM meal_schedules"""
    params = ()
    if date:
        query += " WHERE meal_date = ?"
        params = (date,)
    query += " ORDER BY meal_date, starts_at"
    return jsonify([dict(row) for row in get_db().execute(query, params)])


@api.post("/schedules")
@require_auth
def create_schedule():
    body = json_body()
    required_text = ("date", "meal_type", "starts_at", "ends_at")
    if not body or any(
        not isinstance(body.get(k), str) or not body[k].strip() for k in required_text
    ):
        return error("invalid_request", "date, meal_type, starts_at, ends_at, grade, and class are required")
    try:
        datetime.strptime(body["date"], "%Y-%m-%d")
        meal_status(datetime.strptime("12:00", "%H:%M"), body["starts_at"], body["ends_at"])
        grade, class_number = int(body["grade"]), int(body["class"])
        if not 1 <= grade <= 12 or class_number <= 0:
            raise ValueError("grade and class must be positive integers (grade 1-12)")
    except (KeyError, TypeError, ValueError) as exc:
        if not str(exc):
            exc = ValueError("grade and class must be positive integers (grade 1-12)")
        return error("invalid_request", str(exc))
    db = get_db()
    try:
        cursor = db.execute(
            """INSERT INTO meal_schedules(
                   meal_date, meal_type, grade, class_number, starts_at, ends_at
               ) VALUES (?, ?, ?, ?, ?, ?)""",
            (body["date"], body["meal_type"].strip(), grade, class_number,
             body["starts_at"], body["ends_at"]))
        db.commit()
    except sqlite3.IntegrityError:
        return error("duplicate_schedule", "meal type already exists for this date", 409)
    return jsonify({
        "id": cursor.lastrowid,
        "date": body["date"],
        "meal_type": body["meal_type"].strip(),
        "grade": grade,
        "class": class_number,
        "starts_at": body["starts_at"],
        "ends_at": body["ends_at"],
    }), 201


@api.get("/meals/today")
@require_auth
def today_meals():
    today = datetime.now(configured_timezone(current_app)).date().isoformat()
    rows = get_db().execute(
        """SELECT r.id, r.uid, s.meal_date, s.meal_type, r.served_at
           FROM meal_records r JOIN meal_schedules s ON s.id=r.schedule_id
           WHERE s.meal_date=? ORDER BY r.served_at""", (today,)).fetchall()
    return jsonify([dict(row) for row in rows])


@api.post("/meal/scan")
@require_auth
def scan():
    body = json_body()
    uid = body.get("uid").strip() if body and isinstance(body.get("uid"), str) else ""
    if not uid:
        return error("invalid_request", "uid is required")
    db = get_db()
    student = db.execute(
        "SELECT uid, grade, class_number FROM students WHERE uid=?", (uid,)
    ).fetchone()
    if not student:
        return error("unregistered_card", "card UID is not registered", 404)
    now = datetime.now(configured_timezone(current_app))
    schedule = db.execute(
        """SELECT * FROM meal_schedules
           WHERE meal_date=? AND grade=? AND class_number=?
           ORDER BY starts_at""",
        (now.date().isoformat(), student["grade"], student["class_number"])).fetchall()
    active = next((row for row in schedule if meal_status(now, row["starts_at"], row["ends_at"]) == "approved"), None)
    if active is None:
        if schedule and now.time() < min(parse_hhmm(r["starts_at"]) for r in schedule):
            return error("before_meal_time", "meal service has not started", 403)
        return error("after_meal_time", "meal service has ended", 403)
    duplicate = db.execute(
        """SELECT 1 FROM meal_records r
           JOIN meal_schedules s ON s.id = r.schedule_id
           WHERE r.uid=? AND s.meal_date=?""",
        (uid, now.date().isoformat())).fetchone()
    if duplicate:
        return error("duplicate_same_day", "meal already recorded for this meal", 409)
    served = now.isoformat()
    db.execute("INSERT INTO meal_records(uid, schedule_id, served_at) VALUES (?, ?, ?)",
               (uid, active["id"], served))
    db.commit()
    return jsonify({"code": "approved", "uid": uid, "meal_type": active["meal_type"], "served_at": served}), 201
