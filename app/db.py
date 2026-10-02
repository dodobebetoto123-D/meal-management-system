import os
import sqlite3
from datetime import datetime, timezone
from werkzeug.security import generate_password_hash
from flask import current_app, g


SCHEMA = """
CREATE TABLE IF NOT EXISTS students (
    uid TEXT PRIMARY KEY,
    name TEXT,
    grade INTEGER NOT NULL CHECK (grade BETWEEN 1 AND 12),
    class_number INTEGER NOT NULL CHECK (class_number > 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS meal_schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meal_date TEXT NOT NULL,
    meal_type TEXT NOT NULL,
    grade INTEGER NOT NULL CHECK (grade BETWEEN 1 AND 12),
    class_number INTEGER NOT NULL CHECK (class_number > 0),
    starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    UNIQUE (meal_date, meal_type, grade, class_number)
);
CREATE TABLE IF NOT EXISTS meal_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uid TEXT NOT NULL REFERENCES students(uid),
    schedule_id INTEGER NOT NULL REFERENCES meal_schedules(id),
    served_at TEXT NOT NULL,
    UNIQUE (uid, schedule_id)
);
CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id INTEGER REFERENCES admins(id),
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    details TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_schedules_date ON meal_schedules(meal_date);
CREATE TABLE IF NOT EXISTS admins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS admin_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id INTEGER NOT NULL REFERENCES admins(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_admin_sessions_token ON admin_sessions(token_hash);
CREATE INDEX IF NOT EXISTS idx_admin_sessions_expiry ON admin_sessions(expires_at);
"""


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_error=None):
    db = g.pop("db", None)
    if db:
        db.close()


def init_db():
    db = get_db()
    db.executescript(SCHEMA)
    columns = {row["name"] for row in db.execute("PRAGMA table_info(meal_records)")}
    if "source" not in columns:
        db.execute("ALTER TABLE meal_records ADD COLUMN source TEXT NOT NULL DEFAULT 'scan'")
    student_columns = {row["name"] for row in db.execute("PRAGMA table_info(students)")}
    if "name" not in student_columns:
        db.execute("ALTER TABLE students ADD COLUMN name TEXT")
    username = current_app.config.get("ADMIN_USERNAME") or os.environ.get("ADMIN_USERNAME")
    password = current_app.config.get("ADMIN_PASSWORD") or os.environ.get("ADMIN_PASSWORD")
    admin_exists = db.execute("SELECT 1 FROM admins LIMIT 1").fetchone()
    if username and password and not admin_exists:
        db.execute(
            "INSERT INTO admins(username, password_hash) VALUES (?, ?)",
            (username, generate_password_hash(password)),
        )
    elif not admin_exists and not current_app.config.get("TESTING"):
        raise RuntimeError(
            "No administrator exists. Set ADMIN_USERNAME and ADMIN_PASSWORD for first startup."
        )
    db.commit()
