import sqlite3
from contextlib import contextmanager

from . import config


def connect():
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


@contextmanager
def session():
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with session() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS devices (
                device_id TEXT PRIMARY KEY,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'offline',
                last_hr REAL,
                last_spo2 REAL,
                last_temp REAL,
                last_activity TEXT,
                last_state TEXT,
                last_finger INTEGER
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                device_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_messages_device_ts
                ON messages(device_id, id DESC);

            CREATE TABLE IF NOT EXISTS vitals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                device_id TEXT NOT NULL,
                hr REAL,
                spo2 REAL,
                hrv REAL,
                temp REAL,
                finger INTEGER,
                state TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_vitals_device_ts
                ON vitals(device_id, id DESC);

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                device_id TEXT NOT NULL,
                type TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_events_device_ts
                ON events(device_id, id DESC);

            CREATE TABLE IF NOT EXISTS anomalies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                device_id TEXT NOT NULL,
                score REAL NOT NULL,
                level TEXT NOT NULL,
                reason TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_anomalies_device_ts
                ON anomalies(device_id, id DESC);
            """
        )


def upsert_device(
    device_id,
    ts,
    status=None,
    hr=None,
    spo2=None,
    temp=None,
    activity=None,
    state=None,
    finger=None,
):
    with session() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO devices
                (device_id, first_seen, last_seen, status)
            VALUES (?, ?, ?, ?)
            """,
            (device_id, ts, ts, status or "offline"),
        )
        fields = ["last_seen = ?"]
        values = [ts]
        for column, value in (
            ("status", status),
            ("last_hr", hr),
            ("last_spo2", spo2),
            ("last_temp", temp),
            ("last_activity", activity),
            ("last_state", state),
            ("last_finger", finger),
        ):
            if value is not None:
                fields.append(f"{column} = ?")
                values.append(value)
        values.append(device_id)
        conn.execute(
            f"UPDATE devices SET {', '.join(fields)} WHERE device_id = ?",
            values,
        )


def update_device_status(device_id, status, ts):
    with session() as conn:
        conn.execute(
            """
            UPDATE devices
            SET status = ?, last_seen = ?
            WHERE device_id = ?
            """,
            (status, ts, device_id),
        )


def add_message(device_id, kind, payload, ts):
    with session() as conn:
        conn.execute(
            "INSERT INTO messages (ts, device_id, kind, payload) VALUES (?, ?, ?, ?)",
            (ts, device_id, kind, payload),
        )


def add_vitals(device_id, data, ts):
    hr = data.get("hr")
    spo2 = data.get("spo2")
    hrv = data.get("hrv")
    temp = data.get("temp")
    finger = data.get("finger")
    state = data.get("state")
    with session() as conn:
        conn.execute(
            """
            INSERT INTO vitals
                (ts, device_id, hr, spo2, hrv, temp, finger, state)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (ts, device_id, hr, spo2, hrv, temp, finger, state),
        )
    upsert_device(
        device_id,
        ts,
        status="online",
        hr=hr,
        spo2=spo2,
        temp=temp,
        state=state,
        finger=finger,
    )


def add_event(device_id, event_type, payload, ts):
    with session() as conn:
        conn.execute(
            "INSERT INTO events (ts, device_id, type, payload) VALUES (?, ?, ?, ?)",
            (ts, device_id, event_type, payload),
        )
    upsert_device(device_id, ts, status="online")


def add_anomaly(device_id, score, level, reason, ts):
    with session() as conn:
        conn.execute(
            """
            INSERT INTO anomalies (ts, device_id, score, level, reason)
            VALUES (?, ?, ?, ?, ?)
            """,
            (ts, device_id, score, level, reason),
        )


def get_devices():
    with session() as conn:
        rows = conn.execute(
            "SELECT * FROM devices ORDER BY last_seen DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def get_vitals(device_id=None, limit=200):
    with session() as conn:
        if device_id:
            rows = conn.execute(
                """
                SELECT * FROM vitals
                WHERE device_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (device_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM vitals ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return [dict(row) for row in rows]


def get_messages(device_id=None, limit=200):
    with session() as conn:
        if device_id:
            rows = conn.execute(
                """
                SELECT * FROM messages
                WHERE device_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (device_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM messages ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return [dict(row) for row in rows]


def get_events(device_id=None, limit=100):
    with session() as conn:
        if device_id:
            rows = conn.execute(
                """
                SELECT * FROM events
                WHERE device_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (device_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM events ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return [dict(row) for row in rows]


def get_anomalies(device_id=None, limit=100):
    with session() as conn:
        if device_id:
            rows = conn.execute(
                """
                SELECT * FROM anomalies
                WHERE device_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (device_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM anomalies ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return [dict(row) for row in rows]


def get_stats():
    with session() as conn:
        def scalar(sql):
            return conn.execute(sql).fetchone()[0]

        return {
            "devices": scalar("SELECT COUNT(*) FROM devices"),
            "messages": scalar("SELECT COUNT(*) FROM messages"),
            "vitals": scalar("SELECT COUNT(*) FROM vitals"),
            "events": scalar("SELECT COUNT(*) FROM events"),
            "anomalies": scalar("SELECT COUNT(*) FROM anomalies"),
            "last_message": scalar("SELECT MAX(ts) FROM messages"),
        }


def get_export_vitals():
    with session() as conn:
        rows = conn.execute(
            """
            SELECT ts, device_id, hr, spo2, hrv, temp, finger, state
            FROM vitals
            ORDER BY id ASC
            """
        ).fetchall()
    return [dict(row) for row in rows]
