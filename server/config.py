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
