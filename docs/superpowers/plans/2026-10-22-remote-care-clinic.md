# Remote Care Clinic Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a clinical triage layer over the existing ESP32/MQTT/FastAPI app so a doctor can rank patients, understand why an alert fired, see data trust, and track caregiver action.

**Architecture:** Keep the existing ingest and live dashboard. Add SQLite patient/alert workflow tables, a stateful alert engine in `server/alerts.py`, patient/trend queries in `server/clinic.py`, a 5-second quality monitor, JSON APIs, and three vanilla-JS clinical pages. Triage is the new `/clinic` home; the current dashboard moves to `/live`.

**Tech Stack:** Python 3.12, FastAPI, SQLite (WAL), paho-mqtt, existing personalized model, vanilla HTML/CSS/JS, `unittest`.

**Spec:** `docs/superpowers/specs/2026-10-22-remote-care-clinic-design.md`

> **Implementation status (2026-10-23):** Tasks 1-7 are implemented and their
> backend tests pass. Task 8 API routes and Task 9 demo seed are implemented and
> smoke-tested. Tasks 10-13 have initial pages/assets; remaining work is UI
> hardening and browser verification. Task 14 documentation is in progress.

## Global Constraints

- Reuse the current stack. No new runtime service, build step, JavaScript framework, or CSS framework.
- SQLite writes use the existing `db.session()` context manager and WAL settings.
- Store timestamps as UTC ISO strings. Format them in the browser's local timezone.
- One active wearable per patient; one active patient per device.
- Unbound devices are quarantined: store their raw MQTT data, but create no patient, alert, or clinical status.
- All alert thresholds, windows, and deadlines live in `server/config.py`.
- `X-Demo-Actor` is `doctor` or `caregiver`; it is a demo label, not authentication.
- Existing `/history`, `/api/health`, `/api/vitals`, `/api/messages`, `/api/events`, `/api/anomalies`, `/api/model`, `/api/export.csv`, and `/docs` contract stay unchanged.
- Do not retrain the model or change its 15-feature set.
- No PHI and no WiFi credentials in code, docs, seeds, or screenshots.
- Tests run with `.venv/bin/python -m unittest discover -s tests -v`.
- **Do not run `git commit` or `git push` unless the user explicitly asks.** Tasks therefore end at verification, not at a commit.

## Review Focus

These are the failure modes most likely to bite a user, and the task that pins each one:

1. **A device is bound twice or not bound at all** - task 2 proves duplicate bindings raise `Conflict`, and task 7 proves unbound devices create no alerts.
2. **Overdue and due dates are wrong across timezones** - task 3 tests exact `due_for` values in UTC; task 4 proves overdue is derived from UTC timestamps.
3. **Partial or malformed MQTT payloads** - task 7 tests missing vitals, `finger=0`, invalid JSON, and repeated messages without crashing.
4. **Alert storms and tier changes** - task 4 tests dedupe, supersede, the 10-open cap, comfort suppression, and emergency exemption.
5. **Invalid workflow transitions** - task 8 tests double-resolve, missing resolution note, caregiver response on a doctor-owned task, and unknown ids.

---

### Task 1: Config and Database Foundation

**Files:**
- Modify: `server/config.py`
- Modify: `server/db.py`
- Create: `tests/support.py`
- Create: `tests/test_clinic.py`

**Interfaces:**
- Consumes: existing `server.config`, `server.db.session()`.
- Produces: config constants used by every later task:
  `EMERGENCY_HR_LOW=40`, `EMERGENCY_HR_HIGH=140`, `EMERGENCY_SPO2=88`, `EMERGENCY_TEMP_LOW=35.0`, `EMERGENCY_TEMP_HIGH=39.5`;
  `ACTIONABLE_HR_LOW=50`, `ACTIONABLE_HR_HIGH=120`, `ACTIONABLE_SPO2=92`, `ACTIONABLE_TEMP_LOW=35.5`, `ACTIONABLE_TEMP_HIGH=38.0`;
  `WATCH_HR_LOW=60`, `WATCH_HR_HIGH=100`, `WATCH_SPO2=95`, `WATCH_TEMP_LOW=36.1`, `WATCH_TEMP_HIGH=37.2`;
  `ALERT_BUCKET_SECONDS=10.0`, `ACTIONABLE_WINDOWS=3`, `ACTIONABLE_WINDOWS_REQUIRED=2`, `WATCH_WINDOWS=6`, `WATCH_WINDOWS_REQUIRED=2`;
  `EMERGENCY_WINDOW_SECONDS=30.0`, `EMERGENCY_CONFIRMATIONS=2`, `MODEL_WINDOW_SECONDS=15.0`, `MODEL_WINDOWS=3`, `MODEL_WINDOWS_REQUIRED=2`;
  `TREND_DELTA_PCT=0.20`, `TREND_SUSTAINED_SECONDS=1800.0`, `MOTION_ARTIFACT_G=0.5`;
  `STALE_SECONDS=90.0`, `NO_FINGER_SECONDS=60.0`, `MONITOR_INTERVAL_SECONDS=5.0`, `OPEN_ALERT_CAP=10`, `BASELINE_WINDOWS_REQUIRED=4`;
  `DUE_SECONDS={"emergency":300,"actionable":600,"quality":1800,"watch":86400}`; `CHART_BUCKET_TARGET=200`.
- Produces DB functions used by later tasks: `utc_now() -> str`, `next_patient_id() -> str`, `insert_patient(patient: dict) -> dict`, `update_patient(patient_id: str, fields: dict, now: str | None = None) -> dict | None`, `get_patient(patient_id: str) -> dict | None`, `get_patient_by_name(name: str) -> dict | None`, `list_patients(include_archived: bool = False) -> list[dict]`, `bind_device(patient_id: str, device_id: str, channel: str, now: str | None = None) -> dict`, `unbind_device(patient_id: str, device_id: str, now: str | None = None) -> bool`, `get_active_binding(device_id: str) -> dict | None`, `get_patient_binding(patient_id: str) -> dict | None`, `list_active_bindings() -> list[dict]`, `get_unassigned_devices() -> list[dict]`, `get_device(device_id: str) -> dict | None`, `create_alert(alert: dict) -> int`, `get_alert(alert_id: int) -> dict | None`, `get_open_alerts(patient_id: str | None = None) -> list[dict]`, `get_recent_alerts(patient_id: str, limit: int = 20) -> list[dict]`, `get_open_alert_by_key(dedupe_key: str) -> dict | None`, `get_open_alert_by_kind(patient_id: str, kind: str) -> dict | None`, `count_open_alerts(patient_id: str) -> int`, `update_alert(alert_id: int, fields: dict) -> None`, `add_alert_event(alert_id: int, actor: str, action: str, note: str | None = None, now: str | None = None) -> None`, `get_alert_events_for_patient(patient_id: str, limit: int = 200) -> list[dict]`, `add_note(patient_id: str, author: str, kind: str, text: str, ts: str | None = None) -> dict`, `get_notes(patient_id: str, limit: int = 100) -> list[dict]`, `upsert_baseline(device_id: str, patient_id: str, ready: bool, windows_collected: int, windows_required: int, hr_baseline: float | None = None, spo2_baseline: float | None = None, temp_baseline: float | None = None, calibrated_at: str | None = None, stale: bool = False, now: str | None = None) -> None`, `get_baseline(device_id: str) -> dict | None`, `mark_baselines_stale(now: str | None = None) -> None`, `reset_baseline(device_id: str, now: str | None = None) -> None`, `add_audit(actor: str, entity: str, entity_id: str, action: str, detail: str | dict | None = None, ts: str | None = None) -> None`, `get_audit_for_patient(patient_id: str, limit: int = 200) -> list[dict]`, `get_latest_vital(device_id: str) -> dict | None`, `get_last_finger_positive(device_id: str) -> str | None`, `get_vitals_since(device_id: str, since: str) -> list[dict]`, `get_alerts_since(patient_id: str, since: str) -> list[dict]`.
- Test helper `tests/support.py` produces `DatabaseTestCase` with `self.db_path` and an isolated `config.DB_PATH`.

- [ ] **Step 1: Write the failing schema and binding tests**

```python
# tests/support.py
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server import config, db


class DatabaseTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "test.db"
        self.patcher = patch.object(config, "DB_PATH", self.db_path)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        db.init_db()
```

```python
# tests/test_clinic.py
import sqlite3
import unittest

from server import db
from tests.support import DatabaseTestCase


class SchemaTest(DatabaseTestCase):
    def test_new_tables_exist(self):
        with db.session() as conn:
            names = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        self.assertTrue(
            {
                "patients",
                "patient_devices",
                "alerts",
                "alert_events",
                "notes",
                "baselines",
                "audit_log",
            }
            <= names
        )

    def test_one_active_binding_per_device_and_patient(self):
        first = db.insert_patient(
            {"display_name": "A", "dob": "1940-01-01", "program": "hospice"}
        )
        second = db.insert_patient(
            {"display_name": "B", "dob": "1950-01-01", "program": "telehealth"}
        )
        db.bind_device(first["id"], "sim01", "mdm-g3-pcce/health/sim01")
        with self.assertRaises(sqlite3.IntegrityError):
            db.bind_device(second["id"], "sim01", "mdm-g3-pcce/health/sim01")
        with self.assertRaises(sqlite3.IntegrityError):
            db.bind_device(first["id"], "sim02", "mdm-g3-pcce/health/sim02")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m unittest discover -s tests -p "test_clinic.py" -v`

Expected: FAIL because the new tables and helpers do not exist.

- [ ] **Step 3: Add config constants and the new schema**

Add the constants listed in **Interfaces** to `server/config.py`. In `db.init_db()`, after the existing tables, add exactly these tables/indexes:

```sql
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
```

Implement the DB helpers listed in **Interfaces**. Required behavior:
- `insert_patient` sets `id` with `next_patient_id()` when absent and fills `created_at`/`updated_at` with `utc_now()`.
- `insert_patient` fills defaults: `sex="U"`, `caregiver_available=1`, `comfort_mode=0`, `archived=0`.
- `next_patient_id` returns `PT-0001`, then `PT-0002`, from the highest existing `PT-` id.
- `bind_device` inserts with `bound_at=now`; let `sqlite3.IntegrityError` escape.
- `unbind_device` sets `unbound_at` on the active row and returns whether a row changed.
- `create_alert` inserts the dict, adds `created_at`, `updated_at`, and `last_seen_at` when absent, and returns `lastrowid`.
- `add_audit` JSON-encodes `detail` when it is a dict.
- `upsert_baseline` uses `INSERT ... ON CONFLICT(device_id) DO UPDATE`.
- `get_latest_vital` returns the highest `id` row.
- `get_last_finger_positive` returns `MAX(ts)` where `finger = 1`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m unittest discover -s tests -p "test_clinic.py" -v`

Expected: PASS. Also run the existing suite: `.venv/bin/python -m unittest discover -s tests -v` -> 5 existing tests plus the new tests pass.

---

### Task 2: Patient, Device, Note, and Trend Service

**Files:**
- Create: `server/clinic.py`
- Modify: `tests/test_clinic.py`

**Interfaces:**
- Consumes: Task 1 DB helpers.
- Produces exceptions `ClinicError(status_code=400)`, `NotFound(404)`, `Conflict(409)`, `InvalidState(422)`.
- Produces `channel_for_device(device_id: str) -> str` (`DEFAULT_DEVICE_ID` -> `MQTT_ROOT`; otherwise `MQTT_ROOT/device_id`).
- Produces `normalize_actor(actor: str | None) -> str` (default `doctor`; only `doctor`/`caregiver`).
- Produces `validate_patient_payload(payload: dict, partial: bool = False) -> dict` with allowed fields `display_name`, `dob`, `sex`, `primary_condition`, `reason_for_monitoring`, `medications`, `mobility`, `goals_of_care`, `caregiver_name`, `caregiver_contact`, `caregiver_available`, `program`, `comfort_mode`, `next_review_at`, `archived`.
- Produces `create_patient(payload: dict, now: str | None = None) -> dict`; requires `display_name`, `dob`, `program`, and `device_id`; creates the patient and initial binding; returns the patient row plus `"channel"`; duplicates raise `Conflict`.
- Produces `update_patient(patient_id: str, payload: dict, now: str | None = None) -> dict`.
- Produces `list_patients(include_archived: bool = False, program: str | None = None) -> list[dict]`.
- Produces `get_patient_detail(patient_id: str, now: str | None = None) -> dict` with keys `patient`, `device`, `latest_vital`, `baseline`, `open_alerts`, `recent_alerts`, `notes`.
- Produces `bind_device(patient_id: str, device_id: str, channel: str | None = None, now: str | None = None) -> dict`.
- Produces `unbind_device(patient_id: str, device_id: str, now: str | None = None) -> None`.
- Produces `unassigned_devices() -> list[dict]`.
- Produces `add_note(patient_id: str, author: str, kind: str, text: str, now: str | None = None) -> dict`, `list_notes(patient_id: str) -> list[dict]`.
- Produces `set_follow_up(patient_id: str, next_review_at: str, author: str, note: str | None = None, now: str | None = None) -> dict`.
- Produces `get_trends(patient_id: str, hours: int = 24, now: str | None = None) -> dict` with keys `hours`, `bucket_seconds`, `series` (ascending `ts`, `hr`, `spo2`, `temp`), `baseline` (`hr`, `spo2`, `temp` or null), `band_pct=0.10`, `markers` (`ts`, `type`, `label`).
- Produces `get_patient_audit(patient_id: str) -> list[dict]` merging alert events and audit-log rows, newest first.

- [ ] **Step 1: Write the failing service tests**

Add to `tests/test_clinic.py`:

```python
from server import clinic


class ClinicServiceTest(DatabaseTestCase):
    def test_create_patient_derives_channel_and_id(self):
        patient = clinic.create_patient(
            {
                "display_name": "Demo One",
                "dob": "1942-03-04",
                "program": "hospice",
                "device_id": "sim01",
            }
        )
        self.assertEqual(patient["id"], "PT-0001")
        self.assertEqual(
            patient["channel"], "mdm-g3-pcce/health/sim01"
        )

    def test_create_patient_rejects_duplicate_binding(self):
        first = {"display_name": "A", "dob": "1940-01-01", "program": "hospice"}
        second = {"display_name": "B", "dob": "1950-01-01", "program": "telehealth"}
        clinic.create_patient({**first, "device_id": "sim01"})
        with self.assertRaises(clinic.Conflict):
            clinic.create_patient({**second, "device_id": "sim01"})

    def test_missing_required_fields_raise_400(self):
        with self.assertRaises(clinic.ClinicError) as ctx:
            clinic.create_patient({"display_name": "No DOB", "program": "hospice", "device_id": "sim01"})
        self.assertEqual(ctx.exception.status_code, 400)

    def test_follow_up_requires_iso_timestamp(self):
        patient = clinic.create_patient(
            {"display_name": "A", "dob": "1940-01-01", "program": "telehealth", "device_id": "sim01"}
        )
        with self.assertRaises(clinic.ClinicError):
            clinic.set_follow_up(patient["id"], "tomorrow", "doctor")
        result = clinic.set_follow_up(patient["id"], "2026-11-01T10:00:00+00:00", "doctor", "Call")
        self.assertEqual(result["next_review_at"], "2026-11-01T10:00:00+00:00")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m unittest discover -s tests -p "test_clinic.py" -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'server.clinic'`.

- [ ] **Step 3: Implement `server/clinic.py`**

Implement the interfaces above. Required details:
- `create_patient` derives `channel=channel_for_device(device_id)` and strips `device_id` before inserting the patient row.
- `create_patient` validates `dob` with `datetime.date.fromisoformat`, `program` in `VALID_PROGRAMS`, and `sex` in `{"F","M","O","U"}`.
- `update_patient` rejects `id`, `device_id`, and unknown fields; it sets `updated_at`.
- `get_patient_detail` returns `None`-safe keys: `device` is the active binding or `None`; `latest_vital` and `baseline` are `None` when absent; `recent_alerts` is the newest 20 resolved or open alerts (add `db.get_recent_alerts(patient_id, limit=20)` if needed).
- `bind_device` raises `Conflict` on `sqlite3.IntegrityError` and returns the inserted row.
- `unbind_device` raises `NotFound` if no active row.
- `set_follow_up` parses `datetime.fromisoformat`; stores the normalized ISO string; adds a `follow_up` note when provided.
- `get_trends`: choose `bucket_seconds=max(60, int(hours * 3600 / CHART_BUCKET_TARGET))`; average non-null readings per bucket; markers from `db.get_alerts_since` and notes in the window. Use baseline values from `db.get_baseline`; if absent, return `None` for baseline.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m unittest discover -s tests -p "test_clinic.py" -v`

Expected: PASS.

---

### Task 3: Alert Classification and Sustained Windows

**Files:**
- Create: `server/alerts.py`
- Create: `tests/test_alerts.py`

**Interfaces:**
- Consumes: Task 1 config and DB helpers.
- Produces `TIER_RANK = {"emergency": 0, "actionable": 1, "quality": 2, "watch": 3, "stable": 4, "unknown": 5}`.
- Produces `iso(dt: datetime) -> str` (UTC, `timespec="seconds"`) and `parse_ts(value: str) -> datetime` (UTC-aware).
- Produces `tier_rank(tier: str) -> int`.
- Produces `owner_for(patient: dict) -> str` (`caregiver` only when `patient["caregiver_available"] == 1`).
- Produces `due_for(tier: str, now: datetime) -> str` using `config.DUE_SECONDS`.
- Produces `classify_quality(data: dict, motion_g: float | None) -> str | None`: returns `"motion_artifact"` when usable vitals and `motion_g >= config.MOTION_ARTIFACT_G`; otherwise `None`. It does not own `no_finger`, `stale`, or `offline`.
- Produces `classify_vitals(data: dict) -> dict | None` returning `{"tier","kind","score","reason","value","threshold"}`; priority is emergency > actionable > watch; kinds are `hr`, `spo2`, `temp`.
- Produces `classify_model(result: dict) -> dict | None` returning tier `actionable` for `level="alert"`, `watch` for `level="watch"`, and `kind="model"`.
- Produces `classify_event(event_type: str) -> dict | None`; only `fall` returns an emergency with `kind="fall"`.
- Produces `build_evidence(candidate: dict, data: dict, baseline: dict | None, quality: str = "good") -> dict`.
- Produces `SustainedTracker(bucket_seconds: float)` with `record(now: datetime, tier: str, candidate: dict | None = None) -> None`, `sustained(now: datetime, tier: str, required: int, of: int) -> dict | None`, and `reset() -> None`.

- [ ] **Step 1: Write the failing classification and tracker tests**

```python
# tests/test_alerts.py
import unittest
from datetime import datetime, timedelta, timezone

from server import alerts

NOW = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)


class ClassificationTest(unittest.TestCase):
    def test_emergency_thresholds(self):
        self.assertEqual(alerts.classify_vitals({"hr": 39})["tier"], "emergency")
        self.assertEqual(alerts.classify_vitals({"hr": 141})["tier"], "emergency")
        self.assertEqual(alerts.classify_vitals({"spo2": 87})["tier"], "emergency")
        self.assertEqual(alerts.classify_vitals({"temp": 39.6})["tier"], "emergency")

    def test_actionable_and_watch_thresholds(self):
        self.assertEqual(alerts.classify_vitals({"hr": 125})["tier"], "actionable")
        self.assertEqual(alerts.classify_vitals({"spo2": 91})["tier"], "actionable")
        self.assertEqual(alerts.classify_vitals({"temp": 37.8})["tier"], "watch")
        self.assertIsNone(alerts.classify_vitals({"hr": 75, "spo2": 98, "temp": 36.6}))

    def test_motion_artifact_requires_usable_vitals(self):
        self.assertEqual(
            alerts.classify_quality({"hr": 110, "spo2": 96, "finger": 1}, 0.6),
            "motion_artifact",
        )
        self.assertIsNone(
            alerts.classify_quality({"hr": 110, "spo2": 96, "finger": 0}, 0.6)
        )

    def test_due_for_uses_config(self):
        self.assertEqual(
            alerts.due_for("actionable", NOW),
            "2026-10-22T12:10:00+00:00",
        )


class SustainedTrackerTest(unittest.TestCase):
    def test_two_of_three_buckets(self):
        tracker = alerts.SustainedTracker(10.0)
        tracker.record(NOW, "emergency", {"tier": "emergency"})
        tracker.record(NOW + timedelta(seconds=10), "emergency", {"tier": "emergency"})
        self.assertIsNotNone(tracker.sustained(NOW + timedelta(seconds=20), "emergency", 2, 3))

    def test_two_readings_in_one_bucket_are_not_confirmation(self):
        tracker = alerts.SustainedTracker(10.0)
        tracker.record(NOW, "emergency", {"tier": "emergency"})
        tracker.record(NOW + timedelta(seconds=2), "emergency", {"tier": "emergency"})
        self.assertIsNone(tracker.sustained(NOW + timedelta(seconds=3), "emergency", 2, 3))

    def test_watch_two_of_six(self):
        tracker = alerts.SustainedTracker(10.0)
        tracker.record(NOW, "watch", {"tier": "watch"})
        tracker.record(NOW + timedelta(seconds=50), "watch", {"tier": "watch"})
        self.assertIsNotNone(tracker.sustained(NOW + timedelta(seconds=50), "watch", 2, 6))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m unittest discover -s tests -p "test_alerts.py" -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'server.alerts'`.

- [ ] **Step 3: Implement classification and the tracker**

Required details:
- `classify_vitals` evaluates each signal independently, keeps the highest tier, and picks the most recent/highest signal as `kind`. Use exact reason strings such as `heart rate 39 bpm`, `SpO2 87%`, and `temperature 39.6 C`.
- Emergency checks use the emergency constants; actionable and watch use their constants.
- `SustainedTracker` buckets by `int(now.timestamp() // bucket_seconds)`. Each bucket stores the highest tier and the candidate that produced it. `sustained` counts the last `of` buckets containing at least the requested severity (rank lower or equal) and returns the newest candidate at or above that severity.
- `build_evidence` returns `signal`, `value`, `baseline`, `delta_pct` (null when baseline is null), `duration_s`, `windows`, `quality`, `source`, `model_score`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m unittest discover -s tests -p "test_alerts.py" -v`

Expected: PASS.

---

### Task 4: Alert Lifecycle, Dedupe, and Audit

**Files:**
- Modify: `server/alerts.py`
- Modify: `server/clinic.py`
- Modify: `tests/test_alerts.py`

**Interfaces:**
- Consumes: Tasks 1-3.
- Produces `raise_alert(patient: dict, device_id: str | None, tier: str, kind: str, source: str, reason: str, evidence: dict, score: float | None = None, now: datetime | None = None) -> int | None`.
- Produces `acknowledge_alert(alert_id: int, actor: str, now: datetime | None = None) -> dict`.
- Produces `resolve_alert(alert_id: int, actor: str, note: str, now: datetime | None = None) -> dict`.
- Produces `caregiver_respond(alert_id: int, actor: str, response: str, now: datetime | None = None) -> dict`.
- Produces `reassign_caregiver_alerts(patient_id: str, now: datetime | None = None) -> int`.
- Produces `resolve_quality_for_device(device_id: str, kind: str | None, note: str, now: datetime | None = None) -> int`.
- Produces `decorate_alert(alert: dict, now: datetime | None = None) -> dict` adding `age_s`, `overdue`, `display_status`, `next_action`, `evidence`.
- Produces `decorate_alerts(rows: list[dict], now: datetime | None = None) -> list[dict]`.
- Produces `display_status(alert: dict, now: datetime) -> str`.
- Produces `next_action(tier: str, patient: dict | None = None) -> str`.
- Produces `care_instruction(alert: dict) -> str`.
- Modifies `clinic.update_patient` to call `reassign_caregiver_alerts` when `caregiver_available` changes to 0.
- Modifies `clinic.get_patient_detail` to decorate alerts.
- Raises `clinic.NotFound` for missing alert/patient and `clinic.InvalidState` for illegal transitions.

- [ ] **Step 1: Write the failing workflow tests**

Add to `tests/test_alerts.py`:

```python
from server import clinic, config, db
from tests.support import DatabaseTestCase


class AlertWorkflowTest(DatabaseTestCase):
    def _patient(self, **overrides):
        payload = {
            "display_name": "Demo",
            "dob": "1940-01-01",
            "program": "hospice",
            "device_id": "sim01",
            "caregiver_name": "Sam",
        }
        payload.update(overrides)
        return clinic.create_patient(payload)

    def test_dedupe_updates_open_alert(self):
        patient = self._patient()
        first = alerts.raise_alert(
            patient, "sim01", "actionable", "hr", "rule", "heart rate 125 bpm",
            {"signal": "hr"}, score=0.95, now=NOW,
        )
        second = alerts.raise_alert(
            patient, "sim01", "actionable", "hr", "rule", "heart rate 130 bpm",
            {"signal": "hr"}, score=0.95, now=NOW + timedelta(seconds=5),
        )
        self.assertEqual(first, second)
        self.assertEqual(len(db.get_open_alerts(patient["id"])), 1)

    def test_tier_change_supersedes_old_alert(self):
        patient = self._patient()
        old = alerts.raise_alert(
            patient, "sim01", "watch", "hr", "rule", "heart rate 105 bpm",
            {}, now=NOW,
        )
        new = alerts.raise_alert(
            patient, "sim01", "actionable", "hr", "rule", "heart rate 125 bpm",
            {}, now=NOW + timedelta(seconds=10),
        )
        self.assertNotEqual(old, new)
        self.assertEqual(db.get_alert(old)["status"], "resolved")
        self.assertIn("superseded", db.get_alert(old)["resolution_note"])

    def test_cap_suppresses_only_watch(self):
        patient = self._patient()
        for index in range(config.OPEN_ALERT_CAP):
            db.create_alert(
                {
                    "patient_id": patient["id"],
                    "device_id": "sim01",
                    "tier": "quality",
                    "kind": f"fill{index}",
                    "source": "quality",
                    "status": "open",
                    "owner": "doctor",
                    "reason": "fill",
                    "evidence_json": "{}",
                    "dedupe_key": f"{patient['id']}:fill{index}:quality",
                    "due_at": alerts.due_for("quality", NOW),
                }
            )
        self.assertIsNone(
            alerts.raise_alert(patient, "sim01", "watch", "hr", "rule", "watch", {}, now=NOW)
        )
        self.assertIsNotNone(
            alerts.raise_alert(patient, "sim01", "emergency", "hr", "rule", "emergency", {}, now=NOW)
        )

    def test_comfort_mode_suppresses_watch_with_audit(self):
        patient = self._patient(program="hospice", comfort_mode=1)
        self.assertIsNone(
            alerts.raise_alert(patient, "sim01", "watch", "hr", "rule", "watch", {}, now=NOW)
        )
        audit = db.get_audit_for_patient(patient["id"])
        self.assertEqual(audit[0]["action"], "comfort_suppressed")

    def test_acknowledge_and_resolve(self):
        patient = self._patient()
        alert_id = alerts.raise_alert(
            patient, "sim01", "actionable", "hr", "rule", "high", {}, now=NOW
        )
        ack = alerts.acknowledge_alert(alert_id, "doctor", now=NOW)
        self.assertEqual(ack["status"], "acknowledged")
        self.assertEqual(ack["acknowledged_by"], "doctor")
        with self.assertRaises(clinic.InvalidState):
            alerts.resolve_alert(alert_id, "doctor", "", now=NOW)
        resolved = alerts.resolve_alert(alert_id, "doctor", "Checked", now=NOW)
        self.assertEqual(resolved["status"], "resolved")
        with self.assertRaises(clinic.InvalidState):
            alerts.resolve_alert(alert_id, "doctor", "Again", now=NOW)

    def test_caregiver_cannot_response_on_doctor_owned_alert(self):
        patient = self._patient(caregiver_available=0)
        alert_id = alerts.raise_alert(
            patient, "sim01", "actionable", "hr", "rule", "high", {}, now=NOW
        )
        with self.assertRaises(clinic.InvalidState):
            alerts.caregiver_respond(alert_id, "caregiver", "done", now=NOW)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m unittest discover -s tests -p "test_alerts.py" -v`

Expected: FAIL because the workflow functions do not exist.

- [ ] **Step 3: Implement the workflow**

Required behavior:
- `raise_alert` computes `dedupe_key=f"{patient['id']}:{kind}:{tier}"`. Reuse an existing non-resolved alert with the same key by updating `reason`, `evidence_json`, `score`, `last_seen_at`, and `updated_at`; do not add another `created` event.
- If an open alert with the same `patient_id` and `kind` has a different tier, resolve it with `resolution_note="superseded by <new tier>"`, actor `system`, and a `resolved` event.
- Comfort mode suppresses `watch` only and writes `audit_log(entity="patient", action="comfort_suppressed", detail={"kind":...})`.
- At `config.OPEN_ALERT_CAP`, suppress `watch` only and write `alert_suppressed`; never suppress `quality`, `actionable`, or `emergency`.
- New alerts set `owner=owner_for(patient)`, `status="open"`, `due_at=due_for(tier, now)`, and a `created` event with actor `system`.
- `acknowledge_alert` accepts actor `doctor` only, rejects resolved alerts, and writes an `acknowledged` event.
- `resolve_alert` accepts actor `doctor` only, requires a non-empty note, rejects resolved alerts, and writes a `resolved` event.
- `caregiver_respond` accepts only caregiver-owned unresolved alerts and responses `done`, `cannot`, `contact_doctor`. `done` writes `caregiver_done`. `cannot` and `contact_doctor` write the matching event, move `owner` to `doctor`, and set `due_at=now+600s`.
- `display_status`: overdue -> `Overdue`; acknowledged -> `Acknowledged by <actor>`; caregiver-owned with pending/no response -> `Awaiting caregiver`; caregiver done -> `Caregiver done - doctor review`; otherwise `Needs doctor review`.
- `next_action`: emergency -> `Call caregiver now`; actionable -> `Caregiver check, then doctor review`; quality -> `Restore sensor`; watch -> `Review trend`; stable -> `Next review`.
- `care_instruction` maps kinds: `offline` -> `Check device power and WiFi`; `no_finger` -> `Place a finger on the sensor`; `stale` -> `Check the device is running`; `motion_artifact` -> `Ask the patient to sit still and recheck`; `hr`/`spo2`/`temp` -> `Check the patient and recheck the reading`; `fall` -> `Check on the patient now`; `model` -> `Check the patient and review the trend`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m unittest discover -s tests -p "test_alerts.py" -v`

Expected: PASS.

---

### Task 5: Worklist Ordering and Trust Fields

**Files:**
- Modify: `server/alerts.py`
- Modify: `tests/test_alerts.py`

**Interfaces:**
- Consumes: Tasks 1-4.
- Produces `get_worklist(broker_connected: bool, now: datetime | None = None) -> dict` with `generated_at`, `broker_connected`, `counts` (`patients`, `need_action`, `overdue`, `unknown`), and `patients`.
- Produces `worklist_sort_key(item: dict) -> tuple`.
- Produces `worklist_item(patient: dict, binding: dict | None, device: dict | None, open_alerts: list[dict], latest_vital: dict | None, baseline: dict | None, now: datetime) -> dict`.
- Produces `patient_is_unknown(binding, device, latest_vital, now) -> bool`.

- [ ] **Step 1: Write the failing worklist tests**

```python
class WorklistTest(DatabaseTestCase):
    def test_unknown_without_data_and_quality_above_watch(self):
        unknown = clinic.create_patient(
            {"display_name": "No Data", "dob": "1940-01-01", "program": "telehealth", "device_id": "sim02"}
        )
        quality = clinic.create_patient(
            {"display_name": "Blind", "dob": "1940-01-01", "program": "hospice", "device_id": "sim01"}
        )
        alerts.raise_alert(
            quality, "sim01", "watch", "hr", "rule", "watch", {}, now=NOW
        )
        alerts.raise_alert(
            quality, "sim01", "quality", "offline", "quality", "offline", {}, now=NOW
        )
        result = alerts.get_worklist(True, now=NOW)
        by_name = {row["display_name"]: row for row in result["patients"]}
        self.assertEqual(by_name["No Data"]["tier"], "unknown")
        self.assertEqual(by_name["Blind"]["tier"], "quality")
        self.assertEqual(result["counts"]["unknown"], 1)

    def test_overdue_sorts_before_unacknowledged(self):
        patient = clinic.create_patient(
            {"display_name": "Overdue", "dob": "1940-01-01", "program": "hospice", "device_id": "sim01"}
        )
        alert_id = alerts.raise_alert(
            patient, "sim01", "actionable", "hr", "rule", "high", {},
            now=NOW - timedelta(minutes=20),
        )
        result = alerts.get_worklist(True, now=NOW)
        self.assertEqual(result["patients"][0]["patient_id"], patient["id"])
        self.assertTrue(result["patients"][0]["overdue"])
        self.assertEqual(db.get_alert(alert_id)["status"], "open")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m unittest discover -s tests -p "test_alerts.py" -v`

Expected: FAIL because `get_worklist` does not exist.

- [ ] **Step 3: Implement the worklist**

Required details:
- For each non-archived patient, load active binding, device row, open alerts, latest vital, and baseline.
- `tier` is the worst open tier when any alert is open; otherwise `unknown` when `patient_is_unknown` is true; otherwise `stable`.
- `patient_is_unknown` is true when the binding or device is missing, device status is not `online`, latest vital is missing, latest vital is older than `STALE_SECONDS`, or `latest_vital["finger"] == 0`.
- `counts.unknown` counts patients whose displayed tier is `unknown`.
- `data_quality` is `missing`, `offline`, `stale`, `no_finger`, `motion`, or `good` using the same checks.
- `what_changed` is the newest open alert reason, `No change since last review` when stable, or `No data yet` when unknown.
- `oldest_open_age_s` is the age of the oldest unresolved alert, or `None`.
- `owner` and `status` come from the worst open alert (`decorate_alert`); stable rows use `doctor` and `Stable`.
- `next_action` uses `alerts.next_action`; stable uses `Next review <date>` or `Next review unscheduled`.
- `worklist_sort_key` implements: overdue emergency, overdue actionable, unacknowledged emergency, unacknowledged actionable, acknowledged emergency/actionable, quality, watch, stable. Within a bucket, older first, then name.
- `counts.need_action` counts patients with a quality/actionable/emergency alert or any overdue alert.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m unittest discover -s tests -p "test_alerts.py" -v`

Expected: PASS.

---

### Task 6: Quality Monitor

**Files:**
- Modify: `server/alerts.py`
- Modify: `tests/test_alerts.py`

**Interfaces:**
- Consumes: Tasks 1-5.
- Produces `AlertMonitor(interval: float = config.MONITOR_INTERVAL_SECONDS)` with `start() -> None`, `stop() -> None`, and `run_once(now: datetime | None = None) -> dict` returning `{"created": int, "resolved": int}`.
- Produces `quality_tasks(binding: dict, device: dict, latest_vital: dict | None, last_finger_positive: str | None, now: datetime) -> dict[str, str]` mapping quality kind to reason.

- [ ] **Step 1: Write the failing monitor tests**

```python
class QualityMonitorTest(DatabaseTestCase):
    def test_offline_stale_and_no_finger(self):
        patient = clinic.create_patient(
            {"display_name": "A", "dob": "1940-01-01", "program": "hospice", "device_id": "sim01"}
        )
        db.upsert_device("sim01", alerts.iso(NOW), status="offline")
        monitor = alerts.AlertMonitor()
        self.assertEqual(monitor.run_once(NOW)["created"], 1)
        kinds = {row["kind"] for row in db.get_open_alerts(patient["id"])}
        self.assertIn("offline", kinds)

    def test_no_finger_after_sixty_seconds(self):
        patient = clinic.create_patient(
            {"display_name": "A", "dob": "1940-01-01", "program": "hospice", "device_id": "sim01"}
        )
        db.upsert_device("sim01", alerts.iso(NOW), status="online")
        db.add_vitals(
            "sim01",
            {"hr": None, "spo2": None, "temp": 36.6, "finger": 0},
            alerts.iso(NOW - timedelta(seconds=61)),
        )
        monitor = alerts.AlertMonitor()
        monitor.run_once(NOW)
        kinds = {row["kind"] for row in db.get_open_alerts(patient["id"])}
        self.assertIn("no_finger", kinds)

    def test_good_data_resolves_quality(self):
        patient = clinic.create_patient(
            {"display_name": "A", "dob": "1940-01-01", "program": "hospice", "device_id": "sim01"}
        )
        db.upsert_device("sim01", alerts.iso(NOW), status="online")
        db.add_vitals("sim01", {"hr": 75, "spo2": 98, "temp": 36.6, "finger": 1}, alerts.iso(NOW))
        alerts.raise_alert(
            patient, "sim01", "quality", "stale", "quality", "stale", {}, now=NOW
        )
        self.assertEqual(monitor.run_once(NOW)["resolved"], 1)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m unittest discover -s tests -p "test_alerts.py" -v`

Expected: FAIL because `AlertMonitor` does not exist.

- [ ] **Step 3: Implement the monitor**

Required details:
- Iterate `db.list_active_bindings()`. Load the patient, device, latest vital, and last finger-positive timestamp.
- Offline: create `quality/offline` when `device.status != "online"`.
- Stale: create `quality/stale` when offline is false and the latest vital is missing or older than `STALE_SECONDS`.
- No finger: create `quality/no_finger` when offline/stale are false, latest `finger == 0`, and `now - (last_finger_positive or latest_vital["ts"]) > NO_FINGER_SECONDS`.
- Good data: resolve open `offline`, `stale`, and `no_finger` quality alerts for that patient with note `condition cleared`.
- Use a daemon thread that sleeps `interval` and catches/logs exceptions. `stop()` sets an event and joins.
- `run_once` must be deterministic when `now` is passed.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m unittest discover -s tests -p "test_alerts.py" -v`

Expected: PASS.

---

### Task 7: Ingest Integration and Live Anomaly Preservation

**Files:**
- Modify: `server/mqtt_ingest.py`
- Modify: `server/anomaly.py`
- Modify: `server/main.py`
- Create: `tests/test_ingest.py`

**Interfaces:**
- Consumes: Tasks 1-6.
- Produces `MqttIngestor.engine` (`AlertEngine`) and `MqttIngestor.process_payload(device_id: str, kind: str, payload: str, ts: str | None = None, now: float | None = None) -> None`.
- Produces `AlertEngine.observe_vitals(patient: dict, device_id: str, data: dict, rule_result: dict, motion_g: float | None, now: datetime) -> list[int]`.
- Produces `AlertEngine.observe_model(patient: dict, device_id: str, result: dict, now: datetime) -> list[int]`.
- Produces `AlertEngine.observe_event(patient: dict, device_id: str, event_type: str, now: datetime) -> list[int]`.
- Produces `AlertEngine.set_baseline(device_id: str, baseline: dict, now: datetime) -> None`.
- Produces `AlertEngine.reset(device_id: str) -> None`.
- Modifies `anomaly.evaluate_vitals` to read `config.ACTIONABLE_*` and `config.WATCH_*` instead of literals; its return shape is unchanged.
- Modifies `main.recalibrate` to call `db.reset_baseline`, `ingestor.reset_calibration`, and `ingestor.engine.reset`.

- [ ] **Step 1: Write the failing ingest tests**

```python
# tests/test_ingest.py
import json
import unittest
from datetime import datetime, timedelta, timezone

from server import clinic, config, db
from server.mqtt_ingest import MqttIngestor
from tests.support import DatabaseTestCase

NOW = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)


class IngestTest(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.ingestor = MqttIngestor()

    def test_unbound_device_creates_no_alert(self):
        payload = json.dumps({"hr": 130, "spo2": 96, "temp": 36.8, "finger": 1})
        self.ingestor.process_payload("sim01", "vitals", payload, alerts.iso(NOW), NOW.timestamp())
        self.assertEqual(db.get_open_alerts(), [])

    def test_bound_device_sustained_actionable_alert(self):
        patient = clinic.create_patient(
            {"display_name": "A", "dob": "1940-01-01", "program": "hospice", "device_id": "sim01"}
        )
        payload = json.dumps({"hr": 130, "spo2": 96, "temp": 36.8, "finger": 1})
        self.ingestor.process_payload("sim01", "vitals", payload, alerts.iso(NOW), NOW.timestamp())
        self.ingestor.process_payload(
            "sim01", "vitals", payload, alerts.iso(NOW + 10), NOW.timestamp() + 10
        )
        kinds = {row["kind"] for row in db.get_open_alerts(patient["id"])}
        self.assertIn("hr", kinds)

    def test_fall_event_is_emergency(self):
        patient = clinic.create_patient(
            {"display_name": "A", "dob": "1940-01-01", "program": "hospice", "device_id": "sim01"}
        )
        self.ingestor.process_payload(
            "sim01", "event", json.dumps({"type": "fall"}), alerts.iso(NOW), NOW.timestamp()
        )
        rows = db.get_open_alerts(patient["id"])
        self.assertEqual(rows[0]["tier"], "emergency")
        self.assertEqual(rows[0]["kind"], "fall")

    def test_invalid_json_and_missing_vitals_do_not_crash(self):
        self.ingestor.process_payload("sim01", "vitals", "{", alerts.iso(NOW), NOW.timestamp())
        self.ingestor.process_payload(
            "sim01", "vitals", json.dumps({"finger": 1}), alerts.iso(NOW), NOW.timestamp()
        )
        self.assertEqual(db.get_open_alerts(), [])

    def test_trend_rule_after_thirty_minutes(self):
        patient = clinic.create_patient(
            {"display_name": "A", "dob": "1940-01-01", "program": "telehealth", "device_id": "sim01"}
        )
        self.ingestor.engine.set_baseline(
            "sim01", {"hr": 70, "spo2": 98, "temp": 36.5}, NOW
        )
        data = {"hr": 90, "spo2": 98, "temp": 36.5, "finger": 1}
        self.ingestor.engine.observe_vitals(
            patient, "sim01", data, {}, None, NOW + timedelta(minutes=30)
        )
        self.ingestor.engine.observe_vitals(
            patient, "sim01", data, {}, None, NOW + timedelta(minutes=61)
        )
        kinds = {row["kind"] for row in db.get_open_alerts(patient["id"])}
        self.assertIn("hr", kinds)

    def test_motion_artifact_skips_clinical_alert(self):
        patient = clinic.create_patient(
            {"display_name": "A", "dob": "1940-01-01", "program": "hospice", "device_id": "sim01"}
        )
        self.ingestor.process_payload(
            "sim01", "motion", json.dumps({"ax": 0.0, "ay": 0.0, "az": 3.0, "act": "walk"}),
            alerts.iso(NOW), NOW.timestamp(),
        )
        payload = json.dumps({"hr": 130, "spo2": 96, "temp": 36.8, "finger": 1})
        self.ingestor.process_payload("sim01", "vitals", payload, alerts.iso(NOW), NOW.timestamp())
        self.ingestor.process_payload(
            "sim01", "vitals", payload, alerts.iso(NOW + 10), NOW.timestamp() + 10
        )
        tiers = {row["tier"] for row in db.get_open_alerts(patient["id"])}
        self.assertNotIn("actionable", tiers)
        self.assertIn("quality", tiers)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m unittest discover -s tests -p "test_ingest.py" -v`

Expected: FAIL because `process_payload` and `AlertEngine` do not exist.

- [ ] **Step 3: Implement ingest integration**

Required details:
- `process_payload` contains the logic currently inline in `_on_message`; `_on_message` calls it. Keep storing messages and raw anomalies.
- Track per-device motion deviation as `abs(sqrt(ax**2 + ay**2 + az**2) - 1.0)`; ignore motion older than 30 seconds.
- For vitals, look up the active binding. If unbound, store and return.
- If bound, call `engine.observe_vitals` with the existing `anomaly.evaluate_vitals` result. Do not create clinical alerts when `finger == 0` or `hr`/`spo2` are missing.
- When the model buffer is ready, pass its per-signal centers as the baseline to `engine.set_baseline`. Call `set_baseline` only when the baseline becomes ready or its values change; do not reset the trend clock on every reading. Persist `db.upsert_baseline` on every model update with ready state, collected windows, required windows, baseline values, and `stale=not ready`.
- When `buffer.update` returns a model result, call `engine.observe_model`.
- On a `fall` event, call `engine.observe_event`; keep the existing raw anomaly row.
- `engine.observe_vitals` records the highest candidate in a `SustainedTracker`, then raises:
  - emergency when `sustained(now,"emergency",EMERGENCY_CONFIRMATIONS,3)` with `of=3` (30 seconds at 10-second buckets);
  - otherwise actionable when `sustained(now,"actionable",ACTIONABLE_WINDOWS_REQUIRED,ACTIONABLE_WINDOWS)`;
  - otherwise watch when `sustained(now,"watch",WATCH_WINDOWS_REQUIRED,WATCH_WINDOWS)`.
- `engine.observe_vitals` also runs the trend rule: when a baseline is present and `now - baseline_set_at >= 1800`, a 20% deviation sustained 30 minutes raises a watch alert. Reset the trend timer when the baseline changes.
- `engine.observe_model` uses a separate tracker with `bucket_seconds=MODEL_WINDOW_SECONDS` and raises the model tier when `MODEL_WINDOWS_REQUIRED` of `MODEL_WINDOWS` results agree.
- `engine.observe_vitals` resolves an open `motion_artifact` quality alert when a usable reading arrives without motion artifact.
- `engine.reset` clears trackers, trend state, and baseline for a device.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m unittest discover -s tests -p "test_ingest.py" -v`

Expected: PASS. Then run the full suite.

---

### Task 8: API Routes and Error Mapping

**Files:**
- Modify: `server/main.py`
- Modify: `requirements-dev.txt` (create with `httpx>=0.27`)
- Create: `tests/test_api.py`

**Interfaces:**
- Consumes: Tasks 1-7.
- Produces a global `monitor = AlertMonitor(ingestor.engine)`; lifespan runs `db.init_db()`, `db.mark_baselines_stale()`, `ingestor.start()`, and `monitor.start()`, then stops both on shutdown.
- Produces `actor` dependency from `X-Demo-Actor`.
- Produces routes:
  - `GET /` -> 307 to `/clinic`; `GET /clinic`, `/clinic/patient/{patient_id}`, `/care`, `/live` -> file responses.
  - `GET /api/clinic/worklist`
  - `GET /api/patients?program=&include_archived=`
  - `POST /api/patients`
  - `GET /api/patients/{patient_id}`
  - `PATCH /api/patients/{patient_id}`
  - `POST /api/patients/{patient_id}/devices`
  - `DELETE /api/patients/{patient_id}/devices/{device_id}`
  - `GET /api/patients/{patient_id}/trends?hours=24`
  - `GET /api/patients/{patient_id}/alerts?status=open`
  - `POST /api/alerts/{alert_id}/ack`
  - `POST /api/alerts/{alert_id}/resolve`
  - `POST /api/alerts/{alert_id}/caregiver-response`
  - `GET /api/patients/{patient_id}/notes`
  - `POST /api/patients/{patient_id}/notes`
  - `GET /api/patients/{patient_id}/audit`
  - `POST /api/patients/{patient_id}/follow-up`
  - `GET /api/care/tasks?patient_id=`
  - `GET /api/devices/unassigned`
- Maps `clinic.ClinicError.status_code` to JSON `{"detail": str}`. Maps `sqlite3.Error` to 503.

- [ ] **Step 1: Write the failing API tests**

```python
# tests/test_api.py
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from server import clinic, db, main
from tests.support import DatabaseTestCase


class ApiTest(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.patches = [
            patch.object(main.ingestor, "start", lambda: None),
            patch.object(main.ingestor, "stop", lambda: None),
            patch.object(main.monitor, "start", lambda: None),
            patch.object(main.monitor, "stop", lambda: None),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.client = TestClient(main.app)

    def test_root_redirects_and_pages_exist(self):
        response = self.client.get("/", follow_redirects=False)
        self.assertEqual(response.status_code, 307)
        self.assertEqual(response.headers["location"], "/clinic")
        self.assertEqual(self.client.get("/clinic").status_code, 200)
        self.assertEqual(self.client.get("/live").status_code, 200)

    def test_create_list_and_duplicate(self):
        payload = {
            "display_name": "Demo",
            "dob": "1940-01-01",
            "program": "hospice",
            "device_id": "sim01",
        }
        created = self.client.post("/api/patients", json=payload)
        self.assertEqual(created.status_code, 200)
        self.assertEqual(created.json()["id"], "PT-0001")
        duplicate = self.client.post(
            "/api/patients", json={**payload, "display_name": "Other"}
        )
        self.assertEqual(duplicate.status_code, 409)

    def test_invalid_workflow_transitions(self):
        patient = clinic.create_patient(
            {"display_name": "A", "dob": "1940-01-01", "program": "hospice", "device_id": "sim01"}
        )
        alert_id = 1
        db.create_alert(
            {
                "patient_id": patient["id"], "device_id": "sim01", "tier": "actionable",
                "kind": "hr", "source": "rule", "status": "open", "owner": "doctor",
                "reason": "high", "evidence_json": "{}", "dedupe_key": "x",
                "due_at": "2026-10-22T12:10:00+00:00",
            }
        )
        self.assertEqual(
            self.client.post(f"/api/alerts/{alert_id}/resolve", json={}).status_code, 400
        )
        self.assertEqual(
            self.client.post(f"/api/alerts/{alert_id}/caregiver-response", json={"response": "done"}).status_code, 422
        )

    def test_worklist_and_care_shapes(self):
        clinic.create_patient(
            {"display_name": "A", "dob": "1940-01-01", "program": "hospice", "device_id": "sim01"}
        )
        worklist = self.client.get("/api/clinic/worklist").json()
        self.assertIn("counts", worklist)
        self.assertIn("patients", worklist)
        care = self.client.get("/api/care/tasks?patient_id=PT-0001").json()
        self.assertIn("tasks", care)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m unittest discover -s tests -p "test_api.py" -v`

Expected: FAIL because the routes do not exist.

- [ ] **Step 3: Implement the routes**

Required request bodies:
- `POST /api/patients`: `{"display_name","dob","program","device_id", optional "channel", optional profile/caregiver fields}`.
- `PATCH /api/patients/{id}`: any allowed profile field. Changing `caregiver_available` to 0 reassigns open caregiver alerts.
- `POST /api/patients/{id}/devices`: `{"device_id","channel"?}`.
- `POST /api/alerts/{id}/resolve`: `{"note": "..."}`; empty or missing -> 400.
- `POST /api/alerts/{id}/caregiver-response`: `{"response": "done"|"cannot"|"contact_doctor"}`.
- `POST /api/patients/{id}/notes`: `{"text": "...", "kind": "clinical"|"caregiver"|"visit"|"follow_up"}`.
- `POST /api/patients/{id}/follow-up`: `{"next_review_at": ISO, "note": "..."}`.
- `GET /api/patients/{id}/alerts?status=open|all`: default all, filter open when requested.
- `GET /api/care/tasks`: return `{"patient": ..., "tasks": [...]}` where tasks are decorated open alerts with `instruction` from `care_instruction`.
- `GET /api/devices/unassigned`: return `{"devices": [...]}`.
- Use `Response`/`JSONResponse` and set `cache-control: no-store` on JSON endpoints.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m unittest discover -s tests -p "test_api.py" -v`

Expected: PASS.

---

### Task 9: Demo Seed

**Files:**
- Create: `server/seed.py`
- Create: `tests/test_seed.py`

**Interfaces:**
- Consumes: `clinic.create_patient`, `db.get_patient_by_name`.
- Produces `seed() -> dict` with `{"created": int, "skipped": int}`.
- Seed records:
  - `Demo Patient A`, hospice, `sim01`, caregiver `Sam`, comfort mode 0.
  - `Demo Patient B`, telehealth, `sim02`, caregiver `Riley`, caregiver_available 1.
  - `Demo Patient C`, hospice, `sim03`, caregiver `Jordan`, comfort mode 1.
  - `Demo Patient D`, telehealth, `sim04`, caregiver unavailable.

- [ ] **Step 1: Write the failing seed test**

```python
# tests/test_seed.py
from server import seed
from tests.support import DatabaseTestCase


class SeedTest(DatabaseTestCase):
    def test_seed_is_idempotent(self):
        first = seed.seed()
        second = seed.seed()
        self.assertEqual(first["created"], 4)
        self.assertEqual(second["created"], 0)
        self.assertEqual(second["skipped"], 4)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m unittest discover -s tests -p "test_seed.py" -v`

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `server/seed.py`**

Use `db.get_patient_by_name` to skip existing rows. Create with `clinic.create_patient`; no notes, alerts, or vitals. Add `if __name__ == "__main__": print(seed())`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m unittest discover -s tests -p "test_seed.py" -v`

Expected: PASS.

---

### Task 10: Shared Clinical UI and Navigation

**Files:**
- Create: `server/static/clinic.css`
- Create: `server/static/clinic.js`
- Modify: `health_dashboard.html`
- Modify: `server/static/history.html`

**Interfaces:**
- Consumes: Task 8 JSON APIs.
- Produces `ClinicUI` global with:
  `api(path, options={})`, `esc(value)`, `fmtAge(seconds)`, `fmtDateTime(value)`, `fmtValue(value, digits=0)`, `tierClass(tier)`, `actor()`, `setActor(actor)`, `renderNav(active)`, `poll(fn, ms)`, `drawChart(svg, series, key, options)`, `openDialog(id)`.
- CSS classes: `.clinic-shell`, `.clinic-nav`, `.clinic-banner`, `.clinic-card`, `.clinic-grid`, `.clinic-table`, `.tier-emergency`, `.tier-actionable`, `.tier-quality`, `.tier-watch`, `.tier-stable`, `.tier-unknown`, `.quality-good`, `.quality-warn`, `.quality-bad`, `.btn`, `.btn-ghost`, `.btn-danger`, `.empty-state`, `.patient-card`.
- Navigation on `/live` and `/history` includes `Clinic`.

- [ ] **Step 1: Add the shared assets**

`clinic.css` must support light/dark via `prefers-color-scheme`, 12px/14px/18px type scale, no horizontal scrolling below 700px, and visible focus rings. `clinic.js` must be plain script (no modules) and expose `window.ClinicUI`.

`drawChart(svg, series, key, options)` requirements:
- `series` is an array of `{ts, hr, spo2, temp}`.
- Draw a polyline with a 2px stroke, a baseline dashed line when `options.baseline` is a number, and a translucent band at `baseline * (1 ± options.bandPct)`.
- Markers are vertical dashed lines with a `<title>` label.
- Render `No data` text when there are fewer than two points.

`renderNav(active)` must render `Clinic`, `Live`, `History`, an actor `<select>` (`Doctor`/`Caregiver`) backed by `localStorage["clinic.actor"]`, and a link to `/api/health`. Mark the active link with `aria-current="page"`.

- [ ] **Step 2: Add navigation links to the existing pages**

In `health_dashboard.html`, add `<a class="ghost" href="/clinic">Clinic</a>` to the `.pills` container and change the server route so this file is served at `/live`. In `server/static/history.html`, add `<a href="/clinic">Clinic</a>` to `.nav`.

- [ ] **Step 3: Verify the assets load**

Run: `.venv/bin/python -m uvicorn server.main:app --port 8010`

Then open `http://localhost:8010/live` and `http://localhost:8010/history`; both pages must show a working `Clinic` link, and the console must have no JavaScript errors. Stop the server.

---

### Task 11: Worklist Page and Patient Creation

**Files:**
- Create: `server/static/clinic.html`

**Interfaces:**
- Consumes: `ClinicUI`, `GET /api/clinic/worklist`, `POST /api/patients`.
- Produces a page at `/clinic` with:
  - `#nav`, `#system-banner`, `#counts`, `#filters` (program, owner, status), `#worklist`, `#empty`, `#error`, `#add-patient`, `#patient-dialog`, `#patient-form`, `#patient-summary`, `#confirm-patient`.

- [ ] **Step 1: Build the worklist markup and styles**

Header: `Remote Care Clinic`, subtitle `Who needs attention today?`. System health pill uses `GET /api/health`. Banner text when `broker_connected` is false: `Live data unavailable - clinical status is Unknown`.

Each row/card shows tier, patient name/`PT-xxxx`, program, age, what changed, data-quality badge, baseline state, owner/status, age, next action. Clicking opens `/clinic/patient/{id}`.

- [ ] **Step 2: Implement polling and filters**

`load()` fetches the worklist, renders counts (`N patients · N need action · N overdue · last sync`), applies client-side filters, and re-renders. Compute `last sync` from the newest patient `last_sync`, falling back to `generated_at`. Poll every 10 seconds with `ClinicUI.poll(load, 10000)`. Preserve filter values across reloads.

- [ ] **Step 3: Implement the two-step add-patient dialog**

Step 1 collects name, DOB, program, device ID, caregiver name, caregiver available, and comfort mode. Step 2 shows a summary with name, DOB, program, derived channel `MQTT_ROOT/device_id`, and caregiver. `Confirm` sends `POST /api/patients` and closes only on success. Show server `detail` on 400/409.

- [ ] **Step 4: Playwright spot check**

Start the server, open `/clinic`, verify:
- the empty state or worklist renders without console errors;
- filters change the visible rows;
- adding `Demo UI`, DOB `1940-01-01`, hospice, `sim09` shows the confirmation summary and creates the patient;
- the new patient appears after the next poll.

---

### Task 12: Patient Detail Page

**Files:**
- Create: `server/static/patient.html`

**Interfaces:**
- Consumes: `ClinicUI`, `GET /api/patients/{id}`, `GET /api/patients/{id}/trends?hours=24`, `GET /api/patients/{id}/trends?hours=168`, `GET /api/patients/{id}/audit`, `POST /api/alerts/{id}/ack`, `POST /api/alerts/{id}/resolve`, `POST /api/patients/{id}/notes`, `POST /api/patients/{id}/follow-up`, `POST /api/devices/{device_id}/recalibrate`.
- Produces a page with `#nav`, `#identity`, `#status-strip`, `#alerts`, `#trend-24`, `#trend-7d`, `#baseline`, `#notes`, `#history`, `#actions`, `#resolve-dialog`, `#note-dialog`, `#followup-dialog`.

- [ ] **Step 1: Build the detail layout**

Sections in spec order: identity header, clinical status strip, open alerts, 24-hour trends, 7-day trends, baseline, notes/plan, history, actions. Add a `Live view` link to `/live?patient={id}`. Show `Unknown` for missing/stale values; never carry forward the last value.

- [ ] **Step 2: Implement alert actions**

Each open alert shows tier, reason, evidence (`signal`, `value`, baseline, delta, duration, quality), owner/status, age, and overdue state. Doctor actions: `Acknowledge` calls `/ack`; `Resolve` opens a dialog requiring a note and calls `/resolve`. Refresh the page data after each action.

- [ ] **Step 3: Implement notes, follow-up, baseline, and charts**

`Add note` posts `{"text","kind"}`. `Schedule follow-up` posts an ISO datetime from `<input type="datetime-local">` converted with `new Date(value).toISOString()`. `Recalibrate` calls the existing endpoint and refreshes. Draw both charts with `ClinicUI.drawChart`; show `learning x/y`, `ready`, or `stale - recalibrating`.

- [ ] **Step 4: Playwright spot check**

Open `/clinic/patient/PT-0001` after seeding. Verify:
- identity, status strip, and `Unknown` states render;
- acknowledge and resolve update the alert list;
- a note appears in the notes section;
- both charts render or show `No data`;
- no console errors.

---

### Task 13: Caregiver View

**Files:**
- Create: `server/static/care.html`

**Interfaces:**
- Consumes: `ClinicUI`, `GET /api/care/tasks?patient_id=`, `GET /api/patients`, `POST /api/alerts/{id}/caregiver-response`.
- Produces a page with `#nav`, `#patient-picker`, `#care-header`, `#tasks`, `#empty`, `#error`, and large action buttons.

- [ ] **Step 1: Build the caregiver layout**

If `patient_id` is absent, show a patient `<select>` populated from `/api/patients`; selecting one updates `location.search`. Show `No caregiver assigned - doctor owns these tasks` when `caregiver_available` is 0.

Each task card shows what to check (`instruction`), when it was created, tier in plain language (`Urgent`, `Needs review`, `Sensor issue`), and buttons `Done`, `Cannot do`, `Contact doctor`.

- [ ] **Step 2: Implement actions and polling**

Set the actor to `caregiver` on page load with `ClinicUI.setActor("caregiver")`. Each button posts the matching `response` with the caregiver actor. `Cannot do` and `Contact doctor` move the item to the doctor; `Done` leaves clinical alerts open for doctor review. Poll every 5 seconds with `ClinicUI.poll(load, 5000)`. Show a persistent `Unknown` card when the device is offline.

- [ ] **Step 3: Playwright spot check**

Open `/care?patient=PT-0001`. Verify:
- task cards use plain language and show no model probabilities;
- all three actions post and refresh;
- an offline task says `Check device power and WiFi`;
- no console errors.

---

### Task 14: Documentation and Full Verification

**Files:**
- Modify: `docs/architecture.md`
- Modify: `docs/operations.md`
- Modify: `docs/README.md`
- Modify: `README.md` only if it links to the new routes.

**Interfaces:**
- Consumes: all tasks.
- Produces updated docs covering the clinic layer, seed, monitor, routes, and demo flow.

- [ ] **Step 1: Update the docs**

Add a short architecture section: `MQTT -> raw tables -> alert engine -> alerts/worklist -> clinic/care pages`, with `/live` preserved. Add operations instructions: `python -m server.seed`, start server, run `python simulator.py --device sim01 --scenario stress --duration 60`, and watch the worklist. Document the demo limitation: no auth, no on-call paging, fake data only.

- [ ] **Step 2: Run the full automated suite**

Run: `.venv/bin/python -m unittest discover -s tests -v`

Expected: all tests pass, including the 5 existing model tests.

Run: `.venv/bin/python -m compileall -q server simulator.py`

Expected: exit code 0.

- [ ] **Step 3: Run the end-to-end demo**

```bash
export DB_PATH=/tmp/clinic-demo.db
rm -f "$DB_PATH"
.venv/bin/python -m server.seed
.venv/bin/python -m uvicorn server.main:app --port 8010
```

In a second terminal:

```bash
.venv/bin/python simulator.py --device sim01 --scenario stress --duration 60
```

Verify:
- `/clinic` shows a ranked worklist and a live alert for `Demo Patient A`;
- `/clinic/patient/PT-0001` shows the alert, evidence, and trend;
- `/care?patient=PT-0001` shows the caregiver task and all three actions;
- `/live` still shows the existing vitals dashboard;
- `/history` still shows persisted rows;
- stopping the simulator produces a quality/offline task after the monitor runs.

- [ ] **Step 4: Check the existing API contract**

```bash
curl -s http://localhost:8010/api/health
curl -s http://localhost:8010/api/vitals | head -c 200
curl -s http://localhost:8010/api/anomalies | head -c 200
curl -s http://localhost:8010/api/export.csv | head -2
```

Expected: `ok`/`mqtt_connected`, JSON arrays, and a CSV header. No existing endpoint changes shape.

---

## Plan Self-Review

- **Spec coverage:** Tasks 1-2 cover patients, devices, notes, baselines, audit, and trends. Tasks 3-7 cover tier mapping, quality gate, sustained windows, dedupe/cap/comfort, lifecycle, worklist, monitor, and ingest. Task 8 covers every spec endpoint and error class. Tasks 9-13 cover seed and all three clinical pages plus navigation. Task 14 covers docs and acceptance checks.
- **Type consistency:** `patient["id"]` and `patient["caregiver_available"]` are used consistently. `raise_alert` returns `int | None`; `ack/resolve/caregiver_respond` return decorated alert dicts. `get_worklist` returns the exact JSON shape used by Task 11. `clinic.ClinicError.status_code` is the single API error mapping.
- **Review Focus:** duplicate/unbound devices -> task 2/7; UTC overdue -> task 3/4/5; partial payloads -> task 7; storms/tier changes -> task 4; invalid transitions -> task 8.
- **Proportion:** test assertions and signatures carry the decisions; implementation bodies are left to the engineer except for the schema and threshold values the spec fixes.
