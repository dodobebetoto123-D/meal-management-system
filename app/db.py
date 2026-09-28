import sqlite3
from flask import current_app, g


SCHEMA = """
CREATE TABLE IF NOT EXISTS students (
    uid TEXT PRIMARY KEY,
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
CREATE INDEX IF NOT EXISTS idx_schedules_date ON meal_schedules(meal_date);
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
    get_db().executescript(SCHEMA)
    get_db().commit()
