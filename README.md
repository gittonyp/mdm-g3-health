# MDM G3 Health Monitoring

Multimodal Edge-AI IoT system for personalized patient health monitoring and early anomaly detection.

```text
ESP32 (MAX30102 + MPU6050 + OLED)  ──MQTT──►  HiveMQ broker  ──►  FastAPI server (SQLite + ML + alerts)
Python simulator (virtual ESP32)   ──MQTT──►        │                    │
                                                    └──► Live dashboard  └──► Clinic / Care / History pages
```

- **Device**: ESP32 reads heart rate, SpO2, HRV, and motion (fall detection), and publishes JSON over MQTT.
- **Server**: one FastAPI process subscribes to MQTT, stores data in SQLite, runs rule-based and ML anomaly detection, and serves the web pages and REST API.
- **Simulator**: `simulator.py` impersonates the ESP32, so you can run everything without hardware.

> **Demo only.** There is no authentication, and the default broker (public HiveMQ) is shared and open.
> Use fake data only. This is not a medical device.

More detail lives in [`docs/`](docs/README.md): architecture, edge AI, hardware, operations, experiments, and roadmap.

---

## 1. Prerequisites

| Need | Notes |
|---|---|
| Python 3.11 or newer | Developed on 3.12–3.14 |
| Internet access | The server and simulator connect to `broker.hivemq.com` on TCP port 1883. The browser dashboard uses WebSocket port 8884 or 8000 |
| Git | To clone the repo |
| Docker (optional) | For the container run |
| Arduino IDE (optional) | Only to flash the real ESP32 |

## 2. Setup

```bash
git clone https://github.com/gittonyp/mdm-g3-health.git
cd mdm-g3-health

python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install httpx                    # only needed to run the tests
```

The commands below assume the virtual environment is active. If it isn't, use `.venv/bin/python` and `.venv/bin/uvicorn` instead.

## 3. Run the server

```bash
uvicorn server.main:app --host 127.0.0.1 --port 8000
```

The SQLite database is created at `data/health.db` on first start.

Check that it works:

```bash
curl http://127.0.0.1:8000/api/health
# {"ok":true,"mqtt_connected":true,...}
```

If `mqtt_connected` is `false`, the server cannot reach the broker (firewall, proxy, or no internet).

### Pages

| URL | What it is |
|---|---|
| <http://127.0.0.1:8000/clinic> | Clinic worklist: patients ranked by who needs attention (`/` redirects here) |
| <http://127.0.0.1:8000/clinic/patient/PT-0001> | Patient detail: alerts, evidence, trends, notes |
| <http://127.0.0.1:8000/care?patient=PT-0001> | Caregiver task view |
| <http://127.0.0.1:8000/live> | Raw live vitals dashboard (connects to the broker from the browser) |
| <http://127.0.0.1:8000/history> | Persisted vitals, events, and anomalies |
| <http://127.0.0.1:8000/docs> | Interactive REST API docs |

## 4. Run the full demo (no hardware needed)

Use a scratch database so the demo doesn't pollute `data/health.db`.

**Terminal 1: seed demo patients and start the server**

```bash
export DB_PATH=/tmp/clinic-demo.db      # Windows PowerShell: $env:DB_PATH="C:\temp\clinic-demo.db"
rm -f "$DB_PATH"
python -m server.seed                   # PT-0001 (sim01), PT-0002 (sim02), PT-0003 (esp32 = the real board)
uvicorn server.main:app --port 8010
```

**Terminal 2: publish a virtual patient**

```bash
python simulator.py --device sim01 --scenario stress --duration 60
```

Simulator scenarios: `normal`, `stress`, `fall`, `no_finger`, `offline`. Options: `--device`, `--duration` (seconds), `--host`, `--port`, `--root`.

**Browser**

1. Open <http://127.0.0.1:8010/clinic>. Demo Patient A should rise in the worklist as the stress data arrives.
2. Open the patient page and the caregiver page (`/care?patient=PT-0001`).
3. Stop the simulator. After about 90 seconds the quality monitor raises an offline/stale task.

### Seeing the ML model score

The personalized model needs calibration first:

1. At least 30 s of data for a full feature window.
2. 120 s of *normal* data to calibrate. Run `--scenario normal`, not `stress`, first.
3. After that it scores every 15 s.

For a quick test, shorten calibration:

```bash
MODEL_CALIBRATION_SECONDS=20 uvicorn server.main:app --port 8010
```

Check progress at <http://127.0.0.1:8010/api/model>.

### Live dashboard with the simulator

1. Open `/live`.
2. Click **Add patient**.
3. Enter the MQTT channel `mdm-g3-pcce/health/sim01` (use the device name you started).

## 5. Run the tests

```bash
python -m unittest discover -s tests -v
python -m compileall -q server simulator.py
```

Expected: all 50 tests pass. They use temporary databases and don't need the network.

## 6. Run with Docker (optional)

```bash
docker build -t mdm-g3-health .
docker run --rm -p 10000:10000 mdm-g3-health
```

Open <http://127.0.0.1:10000/>. The image contains only the server, the live dashboard, and the model artifacts. It doesn't include the simulator, firmware, or notebook.

## 7. Real hardware (ESP32)

Parts, wiring, and the full pin table are in [`docs/hardware.md`](docs/hardware.md).

| Part | Pin(s) |
|---|---|
| MAX30102, MPU6050, SSD1306 OLED (I2C) | SDA `D21`, SCL `D22`, 3.3 V, GND |
| Buzzer | `D27` |
| Green LED | `D14` |
| Red LED | `D26` |
| Recalibrate button | `D25` to GND |

Flash steps:

1. In the Arduino IDE, install the **ESP32** board package.
2. Install the libraries `PubSubClient`, `Adafruit SSD1306`, `Adafruit GFX Library`, and `SparkFun MAX3010x Pulse and Proximity Sensor Library`.
3. Open `health_node.ino`.
4. Edit `WIFI_SSID` and `WIFI_PASS` near the top. The ESP32 supports **2.4 GHz WiFi only**.
5. Keep `SIM_MODE 0` for real hardware. Use `1` only for the Wokwi simulator.
6. Select your ESP32 board and serial port, then upload.
7. Open the serial monitor at 115200 baud to check the WiFi and MQTT status.

The firmware publishes to flat topics under `mdm-g3-pcce/health`, so the server records it as device `esp32`. `python -m server.seed` already creates **PT-0003 "ESP32 Board"** bound to that device, so the board shows up on `/clinic` as soon as it publishes. On a database that was seeded before this change, re-run `python -m server.seed`; it only adds what's missing. In `/live`, add a patient with the channel `mdm-g3-pcce/health`.

First-run checklist after flashing:

1. Serial monitor shows WiFi and MQTT connected, and the OLED shows `W:ok M:ok`.
2. `curl http://127.0.0.1:8000/api/devices` lists `esp32` with `status: online`.
3. `/clinic` shows PT-0003 with data (not "No data yet").
4. Keep a finger on the sensor for 2+ minutes of calm, normal readings before expecting an ML score (`/api/model`).

**Temperature (LM35).** The server accepts a `temp` field in the vitals JSON and ignores values outside 25–45 °C (a floating or unplugged ADC pin) instead of raising false alerts. If the firmware can't read it, send `null`. Never send `nan`, because that isn't valid JSON and the whole message is dropped. The ML model needs temperature, so it stays idle until real `temp` values arrive; the rule-based alerts work without it.

## 8. Configuration

All server settings are environment variables (see `server/config.py`).

| Variable | Default | Purpose |
|---|---|---|
| `DB_PATH` | `data/health.db` | SQLite file |
| `MQTT_HOST` / `MQTT_PORT` | `broker.hivemq.com` / `1883` | Broker (plain TCP; the server has no TLS option) |
| `MQTT_ROOT` | `mdm-g3-pcce/health` | Topic root to subscribe to |
| `DEFAULT_DEVICE_ID` | `esp32` | Device ID for flat topics |
| `MODEL_ENABLED` | `1` | `0` turns off ML scoring |
| `MODEL_CALIBRATION_SECONDS` | `0` | `0` uses the artifact default (120 s) |
| `PORT` | `10000` (Docker) | HTTP port in the container |

The simulator reads `MQTT_HOST`, `MQTT_PORT`, and `MQTT_ROOT` too. To use a private broker, set the same values for the server and simulator, and edit them in `health_node.ino`.

## 9. Troubleshooting

| Symptom | Fix |
|---|---|
| `mqtt_connected: false` | Outbound TCP 1883 is blocked or there's no internet. Try another network |
| Nothing appears in `/clinic` | The device must be assigned to a patient. Seeded demo patients use `sim01` and `sim02` |
| `/live` shows "Server offline" | The browser can't reach the broker WebSocket. Try `/live?broker=ws://broker.hivemq.com:8000/mqtt` |
| No ML score | Calibration isn't finished. Check `/api/model` and send 2+ minutes of normal data |
| Temperature shows 37–39 °C with no sensor | Expected. The firmware doesn't send temperature yet, so the dashboard simulates it |
| Port already in use | Use a different `--port` |
| Reset all data | Stop the server and delete the DB file |

## 10. Project status

**Working:** the ESP32 firmware (HR, SpO2, HRV, motion, falls, local alerts), MQTT ingestion, SQLite, REST API, rule-based and ML anomaly detection, the simulator, the live and history pages, the clinic/care layer, Docker and Render configs, and the Colab training notebook. All 50 unit tests pass.

**Not done:**

- **Real temperature.** The LM35 isn't implemented in the firmware.
- **On-device ML.** The TFLite model is exported but isn't integrated into the firmware.
- **Research experiments.** The ablations, robustness, and latency comparisons are missing; see [`docs/experiments.md`](docs/experiments.md).
- **Render deployment.** Not yet verified on a live URL.
- **Hardware-in-the-loop validation** with the real board.

See [`docs/roadmap.md`](docs/roadmap.md) for scope and acceptance criteria.

## Repository layout

```text
health_node.ino          ESP32 firmware
health_dashboard.html    live dashboard (served at /live)
simulator.py             virtual ESP32
server/                  FastAPI app, MQTT ingest, DB, ML model, alerts, clinic logic, static pages
notebooks/               Colab/Kaggle training notebook
data/model_artifacts/    trained models and metrics
tests/                   unit and API tests
docs/                    full documentation, plus the clinic design spec and plan
Dockerfile, render.yaml  deployment
```

## Security note

`health_node.ino` contains WiFi credentials in plain text, and the repo is on public GitHub. Before sharing it further, change the WiFi password and move the credentials to an untracked header file.
