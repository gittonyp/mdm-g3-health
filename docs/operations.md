# Operations and Runbook

How to run, verify, deploy, and troubleshoot the project.

## Prerequisites

- Python 3.11+ (the container uses 3.12)
- Docker (optional, for the container path)
- A Render account (optional, for cloud deployment)
- Network access to `broker.hivemq.com` on port 1883 (server/ESP32) and ports 8884/8000 (browser WebSocket)

Dependencies (`requirements.txt`):

```text
fastapi>=0.115
uvicorn[standard]>=0.30
paho-mqtt>=2.0
```

## Configuration

All server settings are environment variables read in `server/config.py`.

| Variable | Default | Purpose |
|---|---|---|
| `DB_PATH` | `<repo>/data/health.db` | SQLite file path |
| `MQTT_HOST` | `broker.hivemq.com` | Broker host |
| `MQTT_PORT` | `1883` | Broker TCP port |
| `MQTT_ROOT` | `mdm-g3-pcce/health` | Topic root to subscribe |
| `DEFAULT_DEVICE_ID` | `esp32` | Device ID for flat topics |
| `MQTT_CLIENT_ID` | `mdm-g3-server` | Client ID prefix; a random suffix is added |
| `MODEL_ENABLED` | `1` | Set `0` to disable model scoring |
| `MODEL_PATH` | `data/model_artifacts/model_personal_logreg.json` | Model artifact |
| `MODEL_CALIBRATION_SECONDS` | `0` | `0` = use artifact value (120 s); otherwise override |
| `PORT` | `10000` in Docker | HTTP port |

The server connects to MQTT over plain TCP. There is no TLS option in the current code; use port 1883 or add TLS support before pointing it at a TLS-only broker.

## Run locally

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn server.main:app --host 127.0.0.1 --port 8000
```

### Clinic demo

Seed two synthetic patients, start the server, and publish a stress scenario:

```bash
DB_PATH=/tmp/clinic-demo.db .venv/bin/python -m server.seed
DB_PATH=/tmp/clinic-demo.db .venv/bin/uvicorn server.main:app --port 8010
# in a second terminal:
DB_PATH=/tmp/clinic-demo.db .venv/bin/python simulator.py --device sim01 --scenario stress --duration 60
```

Open `/clinic` to review the ranked worklist, `/clinic/patient/PT-0001` for evidence
and trends, `/care?patient=PT-0001` for caregiver actions, and `/live` for the
unchanged raw live dashboard. Stopping a device causes the quality monitor to create
an offline/stale task after its configured timeout.

The clinic is a demo: it has no authentication, on-call paging, or real patient data.
`X-Demo-Actor` is only a UI label and must not be treated as access control.

Useful URLs:

| URL | Purpose |
|---|---|
| <http://127.0.0.1:8000/> | Live dashboard |
| <http://127.0.0.1:8000/history> | Persisted history |
| <http://127.0.0.1:8000/docs> | Interactive API documentation |
| <http://127.0.0.1:8000/api/health> | Server/broker health |
| <http://127.0.0.1:8000/api/model> | Per-device calibration state |
| <http://127.0.0.1:8000/api/export.csv> | CSV of all stored vitals |

Run with a scratch database:

```bash
DB_PATH=/tmp/health.db .venv/bin/uvicorn server.main:app --port 8000
```

## Run a virtual device

The simulator publishes the same MQTT contract as the firmware.

```bash
# Normal patient
.venv/bin/python simulator.py --device sim01 --scenario normal --duration 60

# Stress patient
.venv/bin/python simulator.py --device sim02 --scenario stress --duration 60

# Fall
.venv/bin/python simulator.py --device sim03 --scenario fall --duration 60

# No finger
.venv/bin/python simulator.py --device sim04 --scenario no_finger --duration 60

# Offline/disconnect test: start normal, then stop it
.venv/bin/python simulator.py --device sim05 --scenario normal --duration 30
```

In the dashboard, click **Add patient** and enter:

- Name: anything
- MQTT channel: `mdm-g3-pcce/health/sim01` (or the device you started)

The dashboard subscribes to `{channel}/#`. A patient whose channel is `mdm-g3-pcce/health` receives the flat firmware topics. A patient whose channel includes a device segment receives only that device.

### Calibration timing

The model does not score immediately:

1. The device must publish at least 30 seconds of data before a full feature window exists.
2. Calibration collects normal windows for the first 120 seconds (artifact default) and needs at least 4 windows.
3. Scoring then runs every 15 seconds.

In practice, expect the first model result after roughly 2 to 2.5 minutes of normal data. Check progress at `/api/model`. For quick local tests, shorten the period:

```bash
MODEL_CALIBRATION_SECONDS=20 .venv/bin/uvicorn server.main:app --port 8000
```

With a 20-second override, the model is typically ready after about 45-60 seconds.

## Run with Docker

```bash
docker build -t mdm-g3-health .
docker run --rm -p 10000:10000 mdm-g3-health
```

Open <http://127.0.0.1:10000/>. Override settings as needed:

```bash
docker run --rm -p 10000:10000 \
  -e DB_PATH=/tmp/health.db \
  -e MQTT_HOST=broker.hivemq.com \
  mdm-g3-health
```

The image copies only `server/`, `health_dashboard.html`, and `data/model_artifacts/`. The simulator, notebook, tests, and firmware are not in the image.

## Deploy to Render

The repository includes `render.yaml`, a Render Blueprint definition:

- one Docker web service named `mdm-g3-health`
- free plan
- health check at `/api/health`
- `autoDeploy: true`
- HiveMQ settings and `DB_PATH=/tmp/health.db` as environment variables

Steps:

1. Push the repository to GitHub.
2. In Render, choose **New > Blueprint** and connect the repository, or open:

   <https://render.com/deploy?repo=https://github.com/gittonyp/mdm-g3-health>

3. Approve the service and wait for the image build.
4. Open the service URL.

### Render constraints

- **One HTTP port only.** The free plan does not expose inbound MQTT TCP ports. The ESP32 therefore publishes to HiveMQ, and the Render container connects outbound to HiveMQ. Do not expect to reach a broker running inside Render.
- **Ephemeral filesystem.** `/tmp/health.db` is lost on restart or redeploy. The demo accepts this. Persistent storage requires a paid disk or an external database.
- **Free instance sleep.** After inactivity the service sleeps; MQTT ingestion pauses until it wakes. Retained `online` status on the broker can become stale until the next publish.
- **Build cost.** The image installs Python dependencies at build time; rebuilds happen on each deploy.

## HiveMQ settings

The project uses the public HiveMQ broker for demos.

| Client | Endpoint |
|---|---|
| ESP32 | `broker.hivemq.com:1883` (TCP, plain) |
| Server | `broker.hivemq.com:1883` (TCP, plain) |
| Dashboard | `wss://broker.hivemq.com:8884/mqtt`, fallback `ws://broker.hivemq.com:8000/mqtt` |

The public broker is shared and unauthenticated. Use fake data only.

To use a different broker:

- set `MQTT_HOST`, `MQTT_PORT`, and `MQTT_ROOT` for the server,
- edit the same values in `health_node.ino` for the board,
- append `?broker=wss://your-broker/mqtt` to the dashboard URL.

The dashboard broker override affects only the browser page, not the server.

## Tests and verification

Unit tests:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Current result: 5 tests, all passing (feature extraction, model calibration/scoring, artifact loading, device buffer behavior).

Smoke checks:

```bash
curl -s http://127.0.0.1:8000/api/health
curl -s http://127.0.0.1:8000/api/stats
curl -s http://127.0.0.1:8000/api/devices
curl -s http://127.0.0.1:8000/api/model
```

Expected:

- `/api/health` returns `"ok": true` and `"mqtt_connected": true`.
- `/api/model` shows `"enabled": true` and, after calibration, `"calibration_complete": true`.
- Anomalies appear in `/api/anomalies` and on `/history`.

End-to-end runtime check performed during development:

```bash
MODEL_CALIBRATION_SECONDS=20 DB_PATH=/tmp/plancheck.db \
  .venv/bin/uvicorn server.main:app --port 8011

.venv/bin/python simulator.py --device plancheck --scenario normal  --duration 62
.venv/bin/python simulator.py --device plancheck --scenario stress  --duration 45

curl -s "http://127.0.0.1:8011/api/model"
```

The model calibrated on 4 windows and produced `score 1.0, level alert, source model` for the stress segment.

## Troubleshooting

| Symptom | Check |
|---|---|
| Dashboard says "Server offline" | Browser cannot reach the WebSocket endpoint. Try `?broker=ws://broker.hivemq.com:8000/mqtt`, check firewall/proxy, then reload |
| `/api/health` shows `mqtt_connected: false` | Outbound TCP 1883 blocked, broker outage, or wrong host; check server logs |
| Device missing from dashboard | Patient channel must be the exact topic root used by the device; flat firmware topics map to channel `mdm-g3-pcce/health` |
| Device missing from server | Confirm the server root matches the publish root and `/api/health` shows connected |
| No model score | Calibration incomplete; check `/api/model`; wait 120 s of normal data; ensure `MODEL_ENABLED=1` and the artifact loaded without error |
| Model always alert | Calibration was contaminated by stress or the wrong data; recalibrate and keep the first 120 s normal. Rule alerts also trigger independently |
| Temperature shows 37-39 C with no sensor | Expected: the firmware does not publish `temp`; the dashboard simulates it |
| Temperature is wrong after LM35 | Check ADC pin, 3.3 V supply, conversion formula, and calibrate offset |
| Duplicate anomaly rows | The rule engine and model both emit; publishing is throttled per source/level for 30 s, but database rows can still differ |
| Render data disappeared | `/tmp` is ephemeral on the free plan |
| Render service asleep | Free instances sleep; open the URL to wake it, then restart the device/simulator |
| Server restarted, model not scoring | Per-device calibration buffers are in memory and reset on restart; recalibration starts again automatically |
| `POST .../recalibrate` returns 503 | MQTT is not connected; fix broker connectivity first |
| Port already in use | Use a different `--port` or stop the old process |

## Data management

- Default local database: `data/health.db` (git-ignored).
- Reset: stop the server and delete the database file.
- Export: `GET /api/export.csv` returns all vitals in insertion order.
- Raw audit trail: `messages` table contains every accepted payload.
- No automatic retention; the demo database grows until deleted.
