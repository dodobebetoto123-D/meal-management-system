from datetime import datetime, timedelta, timezone
import hashlib
import secrets
import sqlite3
from functools import wraps
from flask import Blueprint, current_app, flash, g, jsonify, redirect, render_template, request, url_for
from werkzeug.security import check_password_hash

from .db import get_db
from .time_rules import meal_status, parse_hhmm
from . import configured_timezone

api = Blueprint("api", __name__)
web = Blueprint("web", __name__)


def error(code, message, status=400):
    return jsonify({"code": code, "message": message}), status


def json_body():
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else None


def _token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _authenticated_admin(token):
    if not token:
        return None
    now = datetime.now(timezone.utc)
    db = get_db()
    row = db.execute(
        """SELECT a.id, a.username, s.id AS session_id, s.expires_at
           FROM admin_sessions s JOIN admins a ON a.id=s.admin_id
           WHERE s.token_hash=?""",
        (_token_hash(token),),
    ).fetchone()
    if not row:
        return None
    try:
        expires_at = datetime.fromisoformat(row["expires_at"])
    except ValueError:
        expires_at = datetime.min.replace(tzinfo=timezone.utc)
    if expires_at <= now:
        db.execute("DELETE FROM admin_sessions WHERE id=?", (row["session_id"],))
        db.commit()
        return None
    return row


def require_auth(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return error("authentication_required", "Bearer token is required", 401)
        token = header[7:].strip()
        if not token:
            return error("authentication_required", "Bearer token is required", 401)
        row = _authenticated_admin(token)
        if not row:
            return error("authentication_required", "Invalid or expired token", 401)
        g.admin = row
        return view(*args, **kwargs)
    return wrapped


def require_web_auth(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        token = request.cookies.get("admin_token")
        row = _authenticated_admin(token)
        if not row:
            return redirect(url_for("web.login_page", next=request.path))
        g.admin = row
        return view(*args, **kwargs)
    return wrapped


def _audit(action, target_type, target_id, details):
    get_db().execute(
        "INSERT INTO audit_logs(admin_id, action, target_type, target_id, details) VALUES (?, ?, ?, ?, ?)",
        (g.admin["id"], action, target_type, str(target_id), details),
    )


def _validate_student(body):
    uid = body.get("uid", "").strip() if isinstance(body.get("uid"), str) else ""
    name = body.get("name", "").strip() if isinstance(body.get("name"), str) else ""
    try:
        grade, class_number = int(body["grade"]), int(body["class"])
        if not 1 <= len(name) <= 100 or len(uid) > 128 or not uid or not 1 <= grade <= 12 or class_number <= 0:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise ValueError("이름(1~100자), UID, 학년(1~12), 반(양의 정수)을 입력하세요.")
    return uid, name, grade, class_number


def _validate_schedule(body):
    required = ("date", "meal_type", "starts_at", "ends_at")
    if any(not isinstance(body.get(key), str) or not body[key].strip() for key in required):
        raise ValueError("날짜, 급식 유형, 시작 및 종료 시간을 입력하세요.")
    datetime.strptime(body["date"], "%Y-%m-%d")
    meal_status(datetime.strptime("12:00", "%H:%M"), body["starts_at"], body["ends_at"])
    grade, class_number = int(body["grade"]), int(body["class"])
    if not 1 <= grade <= 12 or class_number <= 0:
        raise ValueError("학년은 1~12, 반은 양의 정수여야 합니다.")
    return (body["date"], body["meal_type"].strip(), grade, class_number,
            body["starts_at"], body["ends_at"])


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
        "SELECT uid, name, grade, class_number FROM students ORDER BY grade, class_number, uid"
    ).fetchall()
    return jsonify([dict(row) for row in rows])


@api.post("/students")
@require_auth
def create_student():
    body = json_body()
    try:
        uid, name, grade, class_number = _validate_student(body or {})
    except ValueError as exc:
        return error("invalid_request", str(exc))
    db = get_db()
    try:
        db.execute("INSERT INTO students(uid, name, grade, class_number) VALUES (?, ?, ?, ?)",
                   (uid, name, grade, class_number))
        db.commit()
    except sqlite3.IntegrityError:
        return error("duplicate_student", "uid is already registered", 409)
    return jsonify({"uid": uid, "name": name, "grade": grade, "class": class_number}), 201


@api.put("/students/<path:old_uid>")
@require_auth
def update_student(old_uid):
    body = json_body() or {}
    try:
        uid, name, grade, class_number = _validate_student(body)
    except ValueError as exc:
        return error("invalid_request", str(exc))
    db = get_db()
    if not db.execute("SELECT 1 FROM students WHERE uid=?", (old_uid,)).fetchone():
        return error("not_found", "student not found", 404)
    try:
        db.execute("PRAGMA defer_foreign_keys = ON")
        db.execute("UPDATE students SET uid=?, name=?, grade=?, class_number=? WHERE uid=?",
                   (uid, name, grade, class_number, old_uid))
        db.execute("UPDATE meal_records SET uid=? WHERE uid=?", (uid, old_uid))
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        return error("duplicate_student", "uid is already registered", 409)
    _audit("update", "student", old_uid, f"uid={uid},grade={grade},class={class_number}")
    db.commit()
    return jsonify({"uid": uid, "name": name, "grade": grade, "class": class_number})


@api.delete("/students/<path:uid>")
@require_auth
def delete_student(uid):
    if request.args.get("confirm_uid") != uid:
        return error("confirmation_required", "confirm_uid must exactly match the student UID", 400)
    db = get_db()
    if not db.execute("SELECT 1 FROM students WHERE uid=?", (uid,)).fetchone():
        return error("not_found", "student not found", 404)
    count = db.execute("SELECT COUNT(*) AS count FROM meal_records WHERE uid=?", (uid,)).fetchone()["count"]
    if count:
        return error("student_has_records", "meal records exist; delete records first", 409)
    db.execute("DELETE FROM students WHERE uid=?", (uid,))
    _audit("delete", "student", uid, "student deleted; no meal records existed")
    db.commit()
    return jsonify({"status": "deleted", "uid": uid})


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


@api.put("/schedules/<int:schedule_id>")
@require_auth
def update_schedule(schedule_id):
    body = json_body() or {}
    try:
        values = _validate_schedule(body)
    except (TypeError, ValueError) as exc:
        return error("invalid_request", str(exc))
    db = get_db()
    if not db.execute("SELECT 1 FROM meal_schedules WHERE id=?", (schedule_id,)).fetchone():
        return error("not_found", "schedule not found", 404)
    try:
        db.execute("""UPDATE meal_schedules SET meal_date=?, meal_type=?, grade=?,
                      class_number=?, starts_at=?, ends_at=? WHERE id=?""",
                   (*values, schedule_id))
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        return error("duplicate_schedule", "meal type already exists for this date", 409)
    _audit("update", "schedule", schedule_id, str(values))
    db.commit()
    return jsonify({"id": schedule_id, "date": values[0], "meal_type": values[1],
                    "grade": values[2], "class": values[3], "starts_at": values[4],
                    "ends_at": values[5]})


@api.delete("/schedules/<int:schedule_id>")
@require_auth
def delete_schedule(schedule_id):
    if request.args.get("confirm") != "삭제":
        return error("confirmation_required", "confirm=삭제 is required", 400)
    db = get_db()
    if not db.execute("SELECT 1 FROM meal_schedules WHERE id=?", (schedule_id,)).fetchone():
        return error("not_found", "schedule not found", 404)
    count = db.execute("SELECT COUNT(*) AS count FROM meal_records WHERE schedule_id=?",
                       (schedule_id,)).fetchone()["count"]
    if count:
        return error("schedule_has_records", "meal records exist; schedule cannot be deleted", 409)
    db.execute("DELETE FROM meal_schedules WHERE id=?", (schedule_id,))
    _audit("delete", "schedule", schedule_id, "schedule deleted; no meal records existed")
    db.commit()
    return jsonify({"status": "deleted", "id": schedule_id})


@api.get("/meals/today")
@require_auth
def today_meals():
    today = datetime.now(configured_timezone(current_app)).date().isoformat()
    rows = get_db().execute(
        """SELECT r.id, r.uid, st.name, s.meal_date, s.meal_type, r.served_at, r.source
           FROM meal_records r JOIN meal_schedules s ON s.id=r.schedule_id
           LEFT JOIN students st ON st.uid=r.uid
           WHERE s.meal_date=? ORDER BY r.served_at""", (today,)).fetchall()
    return jsonify([dict(row) for row in rows])


@api.delete("/meals/<int:record_id>")
@require_auth
def delete_meal_record(record_id):
    if request.args.get("confirm") != "삭제":
        return error("confirmation_required", "confirm=삭제 is required", 400)
    db = get_db()
    row = db.execute("SELECT id, uid FROM meal_records WHERE id=?", (record_id,)).fetchone()
    if not row:
        return error("not_found", "meal record not found", 404)
    db.execute("DELETE FROM meal_records WHERE id=?", (record_id,))
    _audit("delete", "meal_record", record_id, f"uid={row['uid']}")
    db.commit()
    return jsonify({"status": "deleted", "id": record_id})


@api.post("/meal/scan")
@require_auth
def scan():
    body = json_body()
    uid = body.get("uid").strip() if body and isinstance(body.get("uid"), str) else ""
    if not uid:
        return error("invalid_request", "uid is required")
    db = get_db()
    student = db.execute(
        "SELECT uid, name, grade, class_number FROM students WHERE uid=?", (uid,)
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
    db.execute("INSERT INTO meal_records(uid, schedule_id, served_at, source) VALUES (?, ?, ?, ?)",
               (uid, active["id"], served, "scan"))
    db.commit()
    return jsonify({"code": "approved", "uid": uid, "name": student["name"],
                    "meal_type": active["meal_type"], "served_at": served}), 201


@web.route("/admin/login", methods=["GET", "POST"])
def login_page():
    if request.method == "POST":
        username, password = request.form.get("username", ""), request.form.get("password", "")
        admin = get_db().execute(
            "SELECT id, username, password_hash FROM admins WHERE username=?", (username,)
        ).fetchone()
        if not admin or not check_password_hash(admin["password_hash"], password):
            flash("아이디 또는 비밀번호가 올바르지 않습니다.", "error")
            return render_template("admin/login.html"), 401
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=current_app.config["SESSION_TTL_SECONDS"]
        )
        db = get_db()
        db.execute("INSERT INTO admin_sessions(admin_id, token_hash, expires_at) VALUES (?, ?, ?)",
                   (admin["id"], _token_hash(token), expires_at.isoformat()))
        db.commit()
        next_path = request.args.get("next", "")
        if not next_path.startswith("/") or next_path.startswith("//"):
            next_path = url_for("web.dashboard")
        response = redirect(next_path)
        response.set_cookie("admin_token", token, max_age=current_app.config["SESSION_TTL_SECONDS"],
                            httponly=True, secure=current_app.config.get("SESSION_COOKIE_SECURE", False),
                            samesite="Lax")
        return response
    return render_template("admin/login.html")


@web.post("/admin/logout")
def web_logout():
    token = request.cookies.get("admin_token")
    if token:
        get_db().execute("DELETE FROM admin_sessions WHERE token_hash=?", (_token_hash(token),))
        get_db().commit()
    response = redirect(url_for("web.login_page"))
    response.delete_cookie("admin_token")
    return response


@web.get("/admin")
@require_web_auth
def dashboard():
    db = get_db()
    students = db.execute(
        "SELECT uid, name, grade, class_number FROM students ORDER BY grade, class_number, uid"
    ).fetchall()
    schedules = db.execute(
        "SELECT id, meal_date, meal_type, grade, class_number, starts_at, ends_at "
        "FROM meal_schedules ORDER BY meal_date DESC, starts_at"
    ).fetchall()
    records = db.execute(
        """SELECT r.id, r.uid, st.name, s.meal_date, s.meal_type, r.served_at, r.source
           FROM meal_records r JOIN meal_schedules s ON s.id=r.schedule_id
           LEFT JOIN students st ON st.uid=r.uid
           ORDER BY r.served_at DESC LIMIT 200"""
    ).fetchall()
    return render_template("admin/dashboard.html", students=students, schedules=schedules,
                           records=records, admin=g.admin)


@web.post("/admin/students/<path:old_uid>/edit")
@require_web_auth
def web_edit_student(old_uid):
    try:
        uid, name, grade, class_number = _validate_student(request.form)
        db = get_db()
        db.execute("PRAGMA defer_foreign_keys = ON")
        db.execute("UPDATE students SET uid=?, name=?, grade=?, class_number=? WHERE uid=?",
                   (uid, name, grade, class_number, old_uid))
        db.execute("UPDATE meal_records SET uid=? WHERE uid=?", (uid, old_uid))
        _audit("update", "student", old_uid, f"uid={uid},grade={grade},class={class_number}")
        db.commit()
        flash("학생 정보를 수정했습니다.", "success")
    except (TypeError, ValueError):
        flash("학생 정보가 올바르지 않습니다.", "error")
    except sqlite3.IntegrityError:
        get_db().rollback()
        flash("이미 사용 중인 UID입니다.", "error")
    return redirect(url_for("web.dashboard"))


@web.post("/admin/students")
@require_web_auth
def web_add_student():
    try:
        uid, name, grade, class_number = _validate_student(request.form)
        db = get_db()
        db.execute(
            "INSERT INTO students(uid, name, grade, class_number) VALUES (?, ?, ?, ?)",
            (uid, name, grade, class_number),
        )
        db.commit()
        flash("학생을 추가했습니다.", "success")
    except (TypeError, ValueError):
        flash("이름(1~100자), UID와 학년(1~12), 반(양의 정수)을 입력하세요.", "error")
    except sqlite3.IntegrityError:
        get_db().rollback()
        flash("이미 등록된 UID입니다.", "error")
    return redirect(url_for("web.dashboard"))


@web.post("/admin/students/<path:uid>/delete")
@require_web_auth
def web_delete_student(uid):
    if request.form.get("confirm_uid") != uid:
        flash("삭제하려면 UID를 정확히 입력해야 합니다.", "error")
        return redirect(url_for("web.dashboard"))
    db = get_db()
    count = db.execute("SELECT COUNT(*) AS count FROM meal_records WHERE uid=?", (uid,)).fetchone()["count"]
    if count:
        flash("식사 기록이 있는 학생은 삭제할 수 없습니다. 기록을 먼저 검토하세요.", "error")
    else:
        db.execute("DELETE FROM students WHERE uid=?", (uid,))
        _audit("delete", "student", uid, "student deleted; no meal records existed")
        db.commit()
        flash("학생을 삭제했습니다.", "success")
    return redirect(url_for("web.dashboard"))


@web.post("/admin/schedules/<int:schedule_id>/edit")
@require_web_auth
def web_edit_schedule(schedule_id):
    try:
        values = _validate_schedule(request.form)
        db = get_db()
        db.execute("""UPDATE meal_schedules SET meal_date=?, meal_type=?, grade=?,
                      class_number=?, starts_at=?, ends_at=? WHERE id=?""",
                   (*values, schedule_id))
        _audit("update", "schedule", schedule_id, str(values))
        db.commit()
        flash("급식 일정을 수정했습니다.", "success")
    except (TypeError, ValueError):
        flash("일정 값이 올바르지 않습니다.", "error")
    except sqlite3.IntegrityError:
        get_db().rollback()
        flash("같은 날짜·급식 유형·학년·반 일정이 이미 있습니다.", "error")
    return redirect(url_for("web.dashboard"))


@web.post("/admin/schedules/<int:schedule_id>/delete")
@require_web_auth
def web_delete_schedule(schedule_id):
    db = get_db()
    count = db.execute("SELECT COUNT(*) AS count FROM meal_records WHERE schedule_id=?",
                       (schedule_id,)).fetchone()["count"]
    if count:
        flash("식사 기록이 연결된 일정은 삭제할 수 없습니다.", "error")
    elif request.form.get("confirm") != "삭제":
        flash("삭제하려면 확인란에 '삭제'를 입력해야 합니다.", "error")
    else:
        db.execute("DELETE FROM meal_schedules WHERE id=?", (schedule_id,))
        _audit("delete", "schedule", schedule_id, "schedule deleted; no meal records existed")
        db.commit()
        flash("급식 일정을 삭제했습니다.", "success")
    return redirect(url_for("web.dashboard"))


@web.post("/admin/meals/<int:record_id>/delete")
@require_web_auth
def web_delete_record(record_id):
    if request.form.get("confirm") != "삭제":
        flash("삭제하려면 확인란에 '삭제'를 입력해야 합니다.", "error")
        return redirect(url_for("web.dashboard"))
    db = get_db()
    row = db.execute("SELECT uid FROM meal_records WHERE id=?", (record_id,)).fetchone()
    if row:
        db.execute("DELETE FROM meal_records WHERE id=?", (record_id,))
        _audit("delete", "meal_record", record_id, f"uid={row['uid']}")
        db.commit()
        flash("잘못된 식사 기록을 삭제했습니다. 감사 로그에 기록되었습니다.", "success")
    else:
        flash("식사 기록을 찾을 수 없습니다.", "error")
    return redirect(url_for("web.dashboard"))
