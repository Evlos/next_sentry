import sqlite3
import os

DB_PATH = os.environ.get("DB_PATH", "data/mini_sentry.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            name      TEXT NOT NULL UNIQUE,
            dsn_key   TEXT NOT NULL UNIQUE,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS events (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id   INTEGER NOT NULL,
            event_id     TEXT,
            level        TEXT DEFAULT 'error',
            title        TEXT,
            message      TEXT,
            culprit      TEXT,
            platform     TEXT,
            environment  TEXT DEFAULT 'production',
            release      TEXT,
            stacktrace   TEXT,
            request_data TEXT,
            extra        TEXT,
            tags         TEXT,
            created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects(id)
        );
    """)
    conn.commit()
    conn.close()
