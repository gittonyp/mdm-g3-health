import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("DB_PATH", str(ROOT_DIR / "data" / "health.db")))
MQTT_HOST = os.getenv("MQTT_HOST", "broker.hivemq.com")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_ROOT = os.getenv("MQTT_ROOT", "mdm-g3-pcce/health").strip("/")
DEFAULT_DEVICE_ID = os.getenv("DEFAULT_DEVICE_ID", "esp32")
MQTT_CLIENT_ID = os.getenv("MQTT_CLIENT_ID", "mdm-g3-server")
MODEL_ENABLED = os.getenv("MODEL_ENABLED", "1").lower() not in {"0", "false", "no"}
MODEL_PATH = Path(
    os.getenv(
        "MODEL_PATH",
        str(ROOT_DIR / "data" / "model_artifacts" / "model_personal_logreg.json"),
    )
)
MODEL_CALIBRATION_SECONDS = float(os.getenv("MODEL_CALIBRATION_SECONDS", "0"))

# Readings outside this range are treated as a faulty sensor (unplugged or floating
# LM35 pin), stored as missing, and never raise a clinical alert.
TEMP_VALID_MIN = 25.0
TEMP_VALID_MAX = 45.0

EMERGENCY_HR_LOW = 40
EMERGENCY_HR_HIGH = 140
EMERGENCY_SPO2 = 88
EMERGENCY_TEMP_LOW = 35.0
EMERGENCY_TEMP_HIGH = 39.5

ACTIONABLE_HR_LOW = 50
ACTIONABLE_HR_HIGH = 120
ACTIONABLE_SPO2 = 92
ACTIONABLE_TEMP_LOW = 35.5
ACTIONABLE_TEMP_HIGH = 38.0

WATCH_HR_LOW = 60
WATCH_HR_HIGH = 100
WATCH_SPO2 = 95
WATCH_TEMP_LOW = 36.1
WATCH_TEMP_HIGH = 37.2

ALERT_BUCKET_SECONDS = 10.0
ACTIONABLE_WINDOWS = 3
ACTIONABLE_WINDOWS_REQUIRED = 2
WATCH_WINDOWS = 6
WATCH_WINDOWS_REQUIRED = 2

EMERGENCY_WINDOW_SECONDS = 30.0
EMERGENCY_CONFIRMATIONS = 2
MODEL_WINDOW_SECONDS = 15.0
MODEL_WINDOWS = 3
MODEL_WINDOWS_REQUIRED = 2

TREND_DELTA_PCT = 0.20
TREND_SUSTAINED_SECONDS = 1800.0
MOTION_ARTIFACT_G = 0.5

STALE_SECONDS = 90.0
NO_FINGER_SECONDS = 60.0
MONITOR_INTERVAL_SECONDS = 5.0
OPEN_ALERT_CAP = 10
BASELINE_WINDOWS_REQUIRED = 4

DUE_SECONDS = {"emergency": 300, "actionable": 600, "quality": 1800, "watch": 86400}
CHART_BUCKET_TARGET = 200
