# Architecture

This document describes the runtime system as implemented in the repository. It is the reference for how data moves from a device to the dashboard, server, database, and model.

## Components

| Component | File(s) | Responsibility |
|---|---|---|
| ESP32 firmware | `health_node.ino` | Reads sensors, detects activity/fall, publishes MQTT, drives buzzer/LEDs/OLED, accepts `recalibrate` |
| Simulator | `simulator.py` | Publishes the same MQTT contract for virtual patients and scripted scenarios |
| Broker | HiveMQ public broker | Routes topics between devices, server, and browser |
| MQTT ingestor | `server/mqtt_ingest.py` | Subscribes to the topic root, persists messages, runs rule and model scoring, publishes anomalies |
| Rule engine | `server/anomaly.py` | Threshold checks for heart rate, SpO2, and temperature |
| Model runtime | `server/model.py` | Feature extraction, per-device calibration, logistic-regression scoring |
| Persistence | `server/db.py` | SQLite schema and queries |
| HTTP API | `server/main.py` | REST endpoints, CSV export, static pages |
| Live dashboard | `health_dashboard.html` | Browser-side MQTT client; patient list, live vitals/motion, events, CSV log |
| History page | `server/static/history.html` | Reads persisted devices/vitals/anomalies through the REST API |
| ML artifacts | `data/model_artifacts/` | Trained model JSON/TFLite, LOSO metrics, predictions, metadata |
| Training notebook | `notebooks/noneeg_training.ipynb` | Colab/Kaggle training, LOSO evaluation, artifact export |

## Data flow

```mermaid
sequenceDiagram
  autonumber
  participant N as ESP32 / simulator
  participant B as HiveMQ
  participant S as FastAPI ingestor
  participant D as SQLite
  participant M as Rule + personal model
  participant W as Browser dashboard
  participant H as /history page

  N->>B: vitals / motion / event / status
  B->>S: root/#
  S->>D: messages, vitals, events, devices
  S->>M: vitals -> rules; rolling windows -> model
  M-->>S: score + level
  S->>D: anomalies
  S->>B: anomaly (only watch/alert, throttled)
  B->>W: live topics
  W->>S: REST (health, stats, devices, anomalies, vitals)
  H->>S: REST (same API)
```

The browser dashboard does **not** receive data through the server. It connects directly to the broker over WebSocket. The server is a separate MQTT subscriber and a REST data store.

## Remote care clinic layer

The clinical workflow is layered over the existing ingest path:

```text
MQTT -> raw tables -> alert engine -> alerts/worklist -> clinic/care pages
```

`/clinic` is the triage worklist, `/clinic/patient/{id}` is the patient detail view,
and `/care` is the caregiver task view. The original live dashboard remains available
at `/live`, and `/history` continues to expose persisted raw readings.

The clinic layer uses the same SQLite database and server process. It adds patient and
device bindings, alert lifecycle events, notes, baselines, audit records, sustained
threshold tracking, and a five-second quality monitor. This is demo workflow logic,
not validated clinical decision support.

## MQTT contract

Topic root: `mdm-g3-pcce/health` (configurable with `MQTT_ROOT`).

Two addressing forms are accepted:

- **Flat (default device)**: `{root}/{kind}`. The server maps this to `DEFAULT_DEVICE_ID` (default `esp32`). This is what the firmware publishes.
- **Per-device**: `{root}/{device_id}/{kind}`. This is what the simulator uses with `--device <id>` and what the dashboard expects when a patient channel includes a device segment.

Kinds and directions:

| Topic suffix | Direction | Payload |
|---|---|---|
| `vitals` | device -> broker | JSON object |
| `motion` | device -> broker | JSON object |
| `event` | device -> broker | JSON object, currently only `{"type":"fall"}` |
| `status` | device -> broker | plain text `online` or `offline`, retained |
| `cmd` | server/dashboard -> device | plain text, currently `recalibrate` |
| `anomaly` | server -> broker | JSON object |

### Vitals

```json
{
  "t": 123456,
  "hr": 74,
  "spo2": 98,
  "hrv": 44,
  "finger": 1,
  "state": "normal",
  "temp": 36.7
}
```

- `t` is device uptime in milliseconds.
- `hr`, `spo2`, `hrv` may be `null` when no finger is detected.
- `state` is one of `normal`, `measuring`, `no_finger`, `alert`, `fall`.
- `temp` is optional. The current firmware does not send it; the dashboard simulates a value when it is absent. The server stores it when present.

### Motion

```json
{
  "t": 123456,
  "ax": 0.03,
  "ay": -0.01,
  "az": 1.0,
  "gx": 1.2,
  "gy": -0.4,
  "gz": 0.8,
  "act": "rest"
}
```

- Acceleration is in g; gyro is in degrees/second.
- `act` is one of `rest`, `walk`, `run`, `fall`.

### Event

```json
{"type": "fall"}
```

### Status and command

Status is plain text, not JSON: `online` or `offline`. It is published as a retained last-will message so a crashed device eventually appears offline. `cmd` is plain text; `recalibrate` resets sensor baselines on the device and resets the server-side model calibration for that device.

### Anomaly

Published by the server when a rule or model result is `watch` or `alert`:

```json
{
  "t": "2026-10-22T13:37:48+00:00",
  "score": 1.0,
  "level": "alert",
  "reason": "personal model stress probability 1.00",
  "source": "model"
}
```

`level` is `watch` or `alert`; `source` is `rule` or `model`.

## Server ingestion pipeline

`MqttIngestor` in `server/mqtt_ingest.py` does the following for every accepted message:

1. Parse the topic into `(device_id, kind)`.
2. Only accept `vitals`, `motion`, `event`, `status`.
3. Insert the raw payload into `messages`.
4. For `status`, update the device row and stop.
5. Parse JSON for the other kinds (invalid JSON is ignored after being stored raw).
6. For `vitals`:
   - Insert into `vitals` and update the device snapshot.
   - Run rule-based checks (`anomaly.evaluate_vitals`).
   - Publish an anomaly if the rule result is not normal.
   - Feed the vitals sample into the per-device model buffer.
7. For `motion`: update activity and feed the sample into the model buffer.
8. For `event`: store it; a `fall` event also writes a 1.0 / `alert` anomaly and marks the device state as `fall`.

### Rule engine

`server/anomaly.py:10` uses fixed thresholds:

| Signal | Watch | Alert |
|---|---|---|
| Heart rate | `< 60` or `> 100` bpm | `< 50` or `> 120` bpm |
| SpO2 | `< 95%` | `< 92%` |
| Temperature | `< 36.1 C` or `> 37.2 C` | `< 35.5 C` or `>= 38.0 C` |

The returned score is the highest triggered severity (0.4-0.45 watch, 0.9-0.95 alert). The rule engine only sees the current sample, not history.

### Personalized model

`server/model.py` implements a per-device state machine:

1. Samples are appended to rolling buffers (vitals and motion), pruned to the 30-second window plus a 5-second margin.
2. Every `step_seconds` (15 s by default) a feature window is computed. A window needs at least 5 samples of each signal.
3. Before the model is calibrated, only windows that the rule engine considers `normal` and that fall inside the calibration period (first 120 s plus one window) are collected.
4. Calibration needs at least 4 feature windows. It computes the median and scaled median absolute deviation (MAD x 1.4826) per feature.
5. After calibration, every new window is z-scored and scored with the logistic-regression coefficients from `data/model_artifacts/model_personal_logreg.json`.
6. Probability `>= 0.8` -> `alert`, `>= 0.5` -> `watch`, otherwise `normal`.

Important properties:

- Calibration state is **in memory per device** and is lost when the server restarts.
- `POST /api/devices/{device_id}/recalibrate` clears the buffer so the device calibrates again.
- `MODEL_CALIBRATION_SECONDS` can override the artifact's calibration period; `0` (default) means "use the artifact value" (120 s).
- The model only runs on `vitals` messages (it is triggered by the vitals arrival), using both vitals and motion buffers.
- Anomaly publishing is throttled: the same `(source, level)` for the same device is suppressed for 30 seconds.

## Persistence schema

SQLite is opened in WAL mode with a 5-second busy timeout (`server/db.py`).

| Table | Key columns | Purpose |
|---|---|---|
| `devices` | `device_id` PK, first/last seen, status, last vitals/activity/state | Current device snapshot |
| `messages` | `ts`, `device_id`, `kind`, `payload` | Raw MQTT payload audit trail |
| `vitals` | `ts`, `device_id`, `hr`, `spo2`, `hrv`, `temp`, `finger`, `state` | Parsed vitals |
| `events` | `ts`, `device_id`, `type`, `payload` | Events such as falls |
| `anomalies` | `ts`, `device_id`, `score`, `level`, `reason` | Rule and model results |

Indexes exist on `(device_id, id DESC)` for messages, vitals, events, and anomalies. There is no retention policy; the demo database grows until it is deleted. On Render the database lives at `/tmp/health.db` and is lost on restart.

## HTTP API

Implemented in `server/main.py`. Interactive docs are available at `/docs`.

| Method | Path | Parameters | Returns |
|---|---|---|---|
| GET | `/` | - | Live dashboard HTML |
| GET | `/history` | - | Server history HTML |
| GET | `/api/health` | - | `ok`, MQTT connection state, broker, root, default device, DB path |
| GET | `/api/config` | - | Root, default device, broker |
| GET | `/api/stats` | - | Row counts and last message time |
| GET | `/api/devices` | - | Device snapshots, newest first |
| GET | `/api/vitals` | `device_id?`, `limit` 1-2000 (default 200) | Vitals, newest first |
| GET | `/api/messages` | `device_id?`, `limit` 1-2000 (default 200) | Raw messages, newest first |
| GET | `/api/events` | `device_id?`, `limit` 1-1000 (default 100) | Events, newest first |
| GET | `/api/anomalies` | `device_id?`, `limit` 1-1000 (default 100) | Anomalies, newest first |
| GET | `/api/model` | - | Model enabled/path/error and per-device calibration state |
| POST | `/api/devices/{device_id}/recalibrate` | - | Publishes `recalibrate`, clears server buffer; 503 if MQTT is down |
| GET | `/api/export.csv` | - | All vitals as CSV |

CSV columns: `time, device_id, heart_rate_bpm, spo2_percent, hrv_ms, temperature_c, finger, state`.

The API has no authentication. Every endpoint, including recalibration and export, is public.

## Dashboard behavior

`health_dashboard.html` is a single-file application:

- Patients are `{name, channel}` pairs stored in `localStorage` (`vitals.patients.v1`), along with the selected patient (`vitals.patient`) and the local event log (`vitals.log.v2`).
- On connect it subscribes to `channel/#` for every patient. The longest matching channel wins when routing an incoming topic.
- It handles `vitals`, `motion`, `event`, `status`, and `anomaly`.
- Temperature is simulated between 37 and 39 C unless a `temp` field arrives in `vitals`.
- An anomaly with `level === "alert"` raises the banner to the `alert` state; `watch` is not visualized separately.
- `recalibrate` publishes `{channel}/cmd` with payload `recalibrate`.
- The CSV button downloads the browser-side event log, not the server database.
- Broker override: append `?broker=wss://host:port/mqtt` to the dashboard URL. Defaults are `wss://broker.hivemq.com:8884/mqtt` and `ws://broker.hivemq.com:8000/mqtt`.

## Trust boundaries and demo scope

- The public HiveMQ broker is unauthenticated and shared. Anyone can read or publish to the topic root. Use fake data only.
- The server accepts any publisher on `{root}/#` as a device.
- The dashboard and API are unauthenticated.
- There is no per-device identity or replay protection; `device_id` is derived entirely from the topic.
- SQLite is not encrypted.

These are deliberate demo trade-offs, not a production security posture.
