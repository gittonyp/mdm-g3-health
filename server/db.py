import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

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

            CREATE TABLE IF NOT EXISTS patients (
                id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                dob TEXT NOT NULL,
                sex TEXT,
                primary_condition TEXT,
                reason_for_monitoring TEXT,
                medications TEXT,
                mobility TEXT,
                goals_of_care TEXT,
                caregiver_name TEXT,
                caregiver_contact TEXT,
                caregiver_available INTEGER NOT NULL DEFAULT 1,
                program TEXT NOT NULL CHECK (program IN ('telehealth', 'hospice')),
                comfort_mode INTEGER NOT NULL DEFAULT 0,
                next_review_at TEXT,
                archived INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS patient_devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_id TEXT NOT NULL,
                device_id TEXT NOT NULL,
                channel TEXT NOT NULL,
                bound_at TEXT NOT NULL,
                unbound_at TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_patient_devices_active_device
                ON patient_devices(device_id) WHERE unbound_at IS NULL;
            CREATE UNIQUE INDEX IF NOT EXISTS idx_patient_devices_active_patient
                ON patient_devices(patient_id) WHERE unbound_at IS NULL;

            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_id TEXT NOT NULL,
                device_id TEXT,
                tier TEXT NOT NULL CHECK (tier IN ('quality', 'watch', 'actionable', 'emergency')),
                kind TEXT NOT NULL,
                source TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('open', 'acknowledged', 'resolved')),
                owner TEXT NOT NULL CHECK (owner IN ('doctor', 'caregiver')),
                caregiver_response TEXT,
                score REAL,
                reason TEXT NOT NULL,
                evidence_json TEXT NOT NULL,
                dedupe_key TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                acknowledged_at TEXT,
                acknowledged_by TEXT,
                resolved_at TEXT,
                resolved_by TEXT,
                resolution_note TEXT,
                due_at TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_alerts_open_dedupe
                ON alerts(dedupe_key) WHERE status != 'resolved';
            CREATE INDEX IF NOT EXISTS idx_alerts_patient_status
                ON alerts(patient_id, status, id DESC);

            CREATE TABLE IF NOT EXISTS alert_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alert_id INTEGER NOT NULL,
                ts TEXT NOT NULL,
                actor TEXT NOT NULL,
                action TEXT NOT NULL,
                note TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_alert_events_alert
                ON alert_events(alert_id, id DESC);

            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_id TEXT NOT NULL,
                ts TEXT NOT NULL,
                author TEXT NOT NULL,
                kind TEXT NOT NULL,
                text TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_notes_patient
                ON notes(patient_id, id DESC);

            CREATE TABLE IF NOT EXISTS baselines (
                device_id TEXT PRIMARY KEY,
                patient_id TEXT NOT NULL,
                ready INTEGER NOT NULL DEFAULT 0,
                windows_collected INTEGER NOT NULL DEFAULT 0,
                windows_required INTEGER NOT NULL DEFAULT 4,
                hr_baseline REAL,
                spo2_baseline REAL,
                temp_baseline REAL,
                calibrated_at TEXT,
                stale INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                actor TEXT NOT NULL,
                entity TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                action TEXT NOT NULL,
                detail TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_audit_patient
                ON audit_log(entity, entity_id, id DESC);
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


PATIENT_FIELDS = (
    "display_name",
    "dob",
    "sex",
    "primary_condition",
    "reason_for_monitoring",
    "medications",
    "mobility",
    "goals_of_care",
    "caregiver_name",
    "caregiver_contact",
    "caregiver_available",
    "program",
    "comfort_mode",
    "next_review_at",
    "archived",
)

ALERT_FIELDS = (
    "patient_id",
    "device_id",
    "tier",
    "kind",
    "source",
    "status",
    "owner",
    "caregiver_response",
    "score",
    "reason",
    "evidence_json",
    "dedupe_key",
    "created_at",
    "updated_at",
    "last_seen_at",
    "acknowledged_at",
    "acknowledged_by",
    "resolved_at",
    "resolved_by",
    "resolution_note",
    "due_at",
)


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def next_patient_id():
    with session() as conn:
        row = conn.execute(
            """
            SELECT MAX(CAST(SUBSTR(id, 4) AS INTEGER))
            FROM patients
            WHERE id LIKE 'PT-%'
            """
        ).fetchone()
    number = (row[0] or 0) + 1
    return f"PT-{number:04d}"


def get_patient(patient_id):
    with session() as conn:
        row = conn.execute(
            "SELECT * FROM patients WHERE id = ?", (patient_id,)
        ).fetchone()
    return dict(row) if row else None


def get_patient_by_name(name):
    with session() as conn:
        row = conn.execute(
            "SELECT * FROM patients WHERE display_name = ? ORDER BY id LIMIT 1",
            (name,),
        ).fetchone()
    return dict(row) if row else None


def list_patients(include_archived=False):
    with session() as conn:
        if include_archived:
            rows = conn.execute(
                "SELECT * FROM patients ORDER BY display_name COLLATE NOCASE, id"
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM patients
                WHERE archived = 0
                ORDER BY display_name COLLATE NOCASE, id
                """
            ).fetchall()
    return [dict(row) for row in rows]


def insert_patient(patient):
    row = dict(patient)
    now = utc_now()
    row.setdefault("id", next_patient_id())
    row.setdefault("sex", "U")
    row.setdefault("caregiver_available", 1)
    row.setdefault("comfort_mode", 0)
    row.setdefault("archived", 0)
    row.setdefault("created_at", now)
    row.setdefault("updated_at", now)
    columns = ("id",) + PATIENT_FIELDS + ("created_at", "updated_at")
    values = [row.get(column) for column in columns]
    with session() as conn:
        conn.execute(
            f"""
            INSERT INTO patients ({", ".join(columns)})
            VALUES ({", ".join("?" for _ in columns)})
            """,
            values,
        )
    return get_patient(row["id"])


def update_patient(patient_id, fields, now=None):
    updates = {
        column: value
        for column, value in fields.items()
        if column in PATIENT_FIELDS
    }
    updates["updated_at"] = now or utc_now()
    columns = list(updates)
    with session() as conn:
        conn.execute(
            f"""
            UPDATE patients
            SET {", ".join(f"{column} = ?" for column in columns)}
            WHERE id = ?
            """,
            [updates[column] for column in columns] + [patient_id],
        )
    return get_patient(patient_id)


def bind_device(patient_id, device_id, channel, now=None):
    ts = now or utc_now()
    with session() as conn:
        cursor = conn.execute(
            """
            INSERT INTO patient_devices (patient_id, device_id, channel, bound_at)
            VALUES (?, ?, ?, ?)
            """,
            (patient_id, device_id, channel, ts),
        )
        binding_id = cursor.lastrowid
        row = conn.execute(
            "SELECT * FROM patient_devices WHERE id = ?", (binding_id,)
        ).fetchone()
    return dict(row)


def unbind_device(patient_id, device_id, now=None):
    ts = now or utc_now()
    with session() as conn:
        cursor = conn.execute(
            """
            UPDATE patient_devices
            SET unbound_at = ?
            WHERE patient_id = ? AND device_id = ? AND unbound_at IS NULL
            """,
            (ts, patient_id, device_id),
        )
        changed = cursor.rowcount > 0
    return changed


def get_active_binding(device_id):
    with session() as conn:
        row = conn.execute(
            """
            SELECT * FROM patient_devices
            WHERE device_id = ? AND unbound_at IS NULL
            ORDER BY id DESC
            LIMIT 1
            """,
            (device_id,),
        ).fetchone()
    return dict(row) if row else None


def get_active_binding_by_channel(channel):
    with session() as conn:
        row = conn.execute(
            """
            SELECT * FROM patient_devices
            WHERE channel = ? AND unbound_at IS NULL
            ORDER BY id DESC
            LIMIT 1
            """,
            (channel,),
        ).fetchone()
    return dict(row) if row else None


def get_patient_binding(patient_id):
    with session() as conn:
        row = conn.execute(
            """
            SELECT * FROM patient_devices
            WHERE patient_id = ? AND unbound_at IS NULL
            ORDER BY id DESC
            LIMIT 1
            """,
            (patient_id,),
        ).fetchone()
    return dict(row) if row else None


def list_active_bindings():
    with session() as conn:
        rows = conn.execute(
            "SELECT * FROM patient_devices WHERE unbound_at IS NULL ORDER BY id"
        ).fetchall()
    return [dict(row) for row in rows]


def get_unassigned_devices():
    with session() as conn:
        rows = conn.execute(
            """
            SELECT * FROM devices AS d
            WHERE NOT EXISTS (
                SELECT 1 FROM patient_devices AS pd
                WHERE pd.device_id = d.device_id AND pd.unbound_at IS NULL
            )
            ORDER BY d.device_id
            """
        ).fetchall()
    return [dict(row) for row in rows]


def get_device(device_id):
    with session() as conn:
        row = conn.execute(
            "SELECT * FROM devices WHERE device_id = ?", (device_id,)
        ).fetchone()
    return dict(row) if row else None


def create_alert(alert):
    row = dict(alert)
    now = utc_now()
    row.setdefault("created_at", now)
    row.setdefault("updated_at", now)
    row.setdefault("last_seen_at", now)
    columns = [column for column in ALERT_FIELDS if column in row]
    with session() as conn:
        cursor = conn.execute(
            f"""
            INSERT INTO alerts ({", ".join(columns)})
            VALUES ({", ".join("?" for _ in columns)})
            """,
            [row[column] for column in columns],
        )
        alert_id = cursor.lastrowid
    return alert_id


def get_alert(alert_id):
    with session() as conn:
        row = conn.execute(
            "SELECT * FROM alerts WHERE id = ?", (alert_id,)
        ).fetchone()
    return dict(row) if row else None


def get_open_alerts(patient_id=None):
    with session() as conn:
        if patient_id is None:
            rows = conn.execute(
                """
                SELECT * FROM alerts
                WHERE status != 'resolved'
                ORDER BY id DESC
                """
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM alerts
                WHERE patient_id = ? AND status != 'resolved'
                ORDER BY id DESC
                """,
                (patient_id,),
            ).fetchall()
    return [dict(row) for row in rows]


def get_recent_alerts(patient_id, limit=20):
    with session() as conn:
        rows = conn.execute(
            """
            SELECT * FROM alerts
            WHERE patient_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (patient_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def get_open_alert_by_key(dedupe_key):
    with session() as conn:
        row = conn.execute(
            """
            SELECT * FROM alerts
            WHERE dedupe_key = ? AND status != 'resolved'
            ORDER BY id DESC
            LIMIT 1
            """,
            (dedupe_key,),
        ).fetchone()
    return dict(row) if row else None


def get_open_alert_by_kind(patient_id, kind):
    with session() as conn:
        row = conn.execute(
            """
            SELECT * FROM alerts
            WHERE patient_id = ? AND kind = ? AND status != 'resolved'
            ORDER BY id DESC
            LIMIT 1
            """,
            (patient_id, kind),
        ).fetchone()
    return dict(row) if row else None


def count_open_alerts(patient_id):
    with session() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) FROM alerts
            WHERE patient_id = ? AND status != 'resolved'
            """,
            (patient_id,),
        ).fetchone()
    return row[0]


def update_alert(alert_id, fields):
    updates = {
        column: value
        for column, value in fields.items()
        if column in ALERT_FIELDS and column not in ("created_at",)
    }
    updates.setdefault("updated_at", utc_now())
    columns = list(updates)
    with session() as conn:
        conn.execute(
            f"""
            UPDATE alerts
            SET {", ".join(f"{column} = ?" for column in columns)}
            WHERE id = ?
            """,
            [updates[column] for column in columns] + [alert_id],
        )


def add_alert_event(alert_id, actor, action, note=None, now=None):
    ts = now or utc_now()
    with session() as conn:
        conn.execute(
            """
            INSERT INTO alert_events (alert_id, ts, actor, action, note)
            VALUES (?, ?, ?, ?, ?)
            """,
            (alert_id, ts, actor, action, note),
        )


def get_alert_events_for_patient(patient_id, limit=200):
    with session() as conn:
        rows = conn.execute(
            """
            SELECT e.* FROM alert_events AS e
            JOIN alerts AS a ON a.id = e.alert_id
            WHERE a.patient_id = ?
            ORDER BY e.id DESC
            LIMIT ?
            """,
            (patient_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def add_note(patient_id, author, kind, text, ts=None):
    ts = ts or utc_now()
    with session() as conn:
        cursor = conn.execute(
            """
            INSERT INTO notes (patient_id, ts, author, kind, text)
            VALUES (?, ?, ?, ?, ?)
            """,
            (patient_id, ts, author, kind, text),
        )
        note_id = cursor.lastrowid
        row = conn.execute(
            "SELECT * FROM notes WHERE id = ?", (note_id,)
        ).fetchone()
    return dict(row)


def get_notes(patient_id, limit=100):
    with session() as conn:
        rows = conn.execute(
            """
            SELECT * FROM notes
            WHERE patient_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (patient_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def upsert_baseline(
    device_id,
    patient_id,
    ready,
    windows_collected,
    windows_required,
    hr_baseline=None,
    spo2_baseline=None,
    temp_baseline=None,
    calibrated_at=None,
    stale=False,
    now=None,
):
    updated_at = now or utc_now()
    with session() as conn:
        conn.execute(
            """
            INSERT INTO baselines (
                device_id, patient_id, ready, windows_collected, windows_required,
                hr_baseline, spo2_baseline, temp_baseline, calibrated_at, stale,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(device_id) DO UPDATE SET
                patient_id = excluded.patient_id,
                ready = excluded.ready,
                windows_collected = excluded.windows_collected,
                windows_required = excluded.windows_required,
                hr_baseline = excluded.hr_baseline,
                spo2_baseline = excluded.spo2_baseline,
                temp_baseline = excluded.temp_baseline,
                calibrated_at = COALESCE(excluded.calibrated_at, baselines.calibrated_at),
                stale = excluded.stale,
                updated_at = excluded.updated_at
            """,
            (
                device_id,
                patient_id,
                int(bool(ready)),
                windows_collected,
                windows_required,
                hr_baseline,
                spo2_baseline,
                temp_baseline,
                calibrated_at,
                int(bool(stale)),
                updated_at,
            ),
        )


def get_baseline(device_id):
    with session() as conn:
        row = conn.execute(
            "SELECT * FROM baselines WHERE device_id = ?", (device_id,)
        ).fetchone()
    return dict(row) if row else None


def mark_baselines_stale(now=None):
    updated_at = now or utc_now()
    with session() as conn:
        conn.execute(
            "UPDATE baselines SET stale = 1, updated_at = ?", (updated_at,)
        )


def reset_baseline(device_id, now=None):
    with session() as conn:
        conn.execute("DELETE FROM baselines WHERE device_id = ?", (device_id,))


def add_audit(actor, entity, entity_id, action, detail=None, ts=None):
    if isinstance(detail, dict):
        detail = json.dumps(detail)
    timestamp = ts or utc_now()
    with session() as conn:
        conn.execute(
            """
            INSERT INTO audit_log (ts, actor, entity, entity_id, action, detail)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (timestamp, actor, entity, entity_id, action, detail),
        )


def get_audit_for_patient(patient_id, limit=200):
    with session() as conn:
        rows = conn.execute(
            """
            SELECT * FROM audit_log
            WHERE entity = 'patient' AND entity_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (patient_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def get_latest_vital(device_id):
    with session() as conn:
        row = conn.execute(
            """
            SELECT * FROM vitals
            WHERE device_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (device_id,),
        ).fetchone()
    return dict(row) if row else None


def get_last_finger_positive(device_id):
    with session() as conn:
        row = conn.execute(
            """
            SELECT MAX(ts) FROM vitals
            WHERE device_id = ? AND finger = 1
            """,
            (device_id,),
        ).fetchone()
    return row[0]


def get_vitals_since(device_id, since):
    with session() as conn:
        rows = conn.execute(
            """
            SELECT * FROM vitals
            WHERE device_id = ? AND ts >= ?
            ORDER BY id ASC
            """,
            (device_id, since),
        ).fetchall()
    return [dict(row) for row in rows]


def get_alerts_since(patient_id, since):
    with session() as conn:
        rows = conn.execute(
            """
            SELECT * FROM alerts
            WHERE patient_id = ? AND created_at >= ?
            ORDER BY id ASC
            """,
            (patient_id, since),
        ).fetchall()
    return [dict(row) for row in rows]
