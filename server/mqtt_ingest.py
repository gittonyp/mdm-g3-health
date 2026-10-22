import json
import logging
import time
import uuid
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

from . import anomaly, config, db
from .model import DeviceBuffer, PersonalizedModel


logger = logging.getLogger(__name__)


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class MqttIngestor:
    def __init__(self):
        client_id = f"{config.MQTT_CLIENT_ID}-{uuid.uuid4().hex[:6]}"
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
        )
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.connected = False
        self._last_anomaly = {}
        self.model = None
        self.model_error = None
        self.device_buffers = {}
        if config.MODEL_ENABLED:
            try:
                self.model = PersonalizedModel.from_file(config.MODEL_PATH)
            except (OSError, ValueError, KeyError) as exc:
                self.model_error = str(exc)
                logger.warning("personal model disabled: %s", exc)

    def start(self):
        self.client.connect_async(
            config.MQTT_HOST,
            config.MQTT_PORT,
            keepalive=30,
        )
        self.client.loop_start()

    def stop(self):
        self.client.loop_stop()
        self.client.disconnect()

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        self.connected = getattr(reason_code, "value", reason_code) == 0
        if self.connected:
            client.subscribe(f"{config.MQTT_ROOT}/#", qos=0)

    def _on_disconnect(self, client, userdata, *args):
        self.connected = False

    def _on_message(self, client, userdata, msg):
        parsed = self._parse_topic(msg.topic)
        if not parsed:
            return
        device_id, kind = parsed
        if kind not in {"vitals", "motion", "event", "status"}:
            return

        ts = utc_now()
        now = time.time()
        payload = msg.payload.decode("utf-8", errors="replace")
        db.add_message(device_id, kind, payload, ts)

        if kind == "status":
            status = payload.strip().lower()
            if status not in {"online", "offline"}:
                status = "online"
            db.update_device_status(device_id, status, ts)
            return

        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return

        if kind == "vitals":
            result = anomaly.evaluate_vitals(
                data.get("hr"),
                data.get("spo2"),
                data.get("temp"),
            )
            db.add_vitals(device_id, data, ts)
            if result["level"] != "normal":
                self._maybe_publish_anomaly(client, device_id, result, ts)
            self._update_model(client, device_id, now, data, result["level"], ts)
        elif kind == "motion":
            db.upsert_device(
                device_id,
                ts,
                status="online",
                activity=data.get("act"),
            )
            buffer = self._buffer(device_id)
            if buffer:
                buffer.add_motion(now, data)
        elif kind == "event":
            event_type = str(data.get("type", "event"))
            db.add_event(device_id, event_type, payload, ts)
            if event_type == "fall":
                db.add_anomaly(device_id, 1.0, "alert", "fall detected", ts)
                db.upsert_device(device_id, ts, status="online", state="fall")

    def _buffer(self, device_id):
        if not self.model:
            return None
        buffer = self.device_buffers.get(device_id)
        if buffer is None:
            buffer = DeviceBuffer(
                self.model,
                calibration_seconds=config.MODEL_CALIBRATION_SECONDS or None,
            )
            self.device_buffers[device_id] = buffer
        return buffer

    def _update_model(self, client, device_id, now, data, rule_level, ts):
        buffer = self._buffer(device_id)
        if buffer is None:
            return
        buffer.add_vitals(now, data)
        result = buffer.update(now, rule_level)
        if result and result["level"] != "normal":
            self._maybe_publish_anomaly(client, device_id, result, ts)

    def reset_calibration(self, device_id):
        self.device_buffers.pop(device_id, None)

    def model_status(self):
        return {
            "enabled": self.model is not None,
            "path": str(config.MODEL_PATH),
            "error": self.model_error,
            "devices": {
                device_id: buffer.status()
                for device_id, buffer in self.device_buffers.items()
            },
        }

    def _maybe_publish_anomaly(self, client, device_id, result, ts):
        key = (result.get("source", "rule"), result["level"])
        previous = self._last_anomaly.get(device_id)
        now = time.monotonic()
        if previous and previous[0] == key and now - previous[1] < 30:
            return
        self._last_anomaly[device_id] = (key, now)
        db.add_anomaly(
            device_id,
            result["score"],
            result["level"],
            result["reason"],
            ts,
        )
        payload = json.dumps(
            {
                "t": ts,
                "score": result["score"],
                "level": result["level"],
                "reason": result["reason"],
                "source": result.get("source", "rule"),
            }
        )
        client.publish(
            self._device_topic(device_id, "anomaly"),
            payload,
            qos=0,
        )

    def _parse_topic(self, topic):
        prefix = f"{config.MQTT_ROOT}/"
        if not topic.startswith(prefix):
            return None
        parts = topic[len(prefix):].split("/")
        if len(parts) == 1 and parts[0]:
            return config.DEFAULT_DEVICE_ID, parts[0]
        if len(parts) == 2 and parts[0] and parts[1]:
            return parts[0], parts[1]
        return None

    def _device_topic(self, device_id, kind):
        if device_id == config.DEFAULT_DEVICE_ID:
            return f"{config.MQTT_ROOT}/{kind}"
        return f"{config.MQTT_ROOT}/{device_id}/{kind}"

    def publish_cmd(self, device_id, command):
        return self.client.publish(
            self._device_topic(device_id, "cmd"),
            command,
            qos=0,
        )
