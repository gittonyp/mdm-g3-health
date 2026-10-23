import json
import logging
import time
import uuid
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

from . import alerts, anomaly, config, db
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
        self.engine = alerts.AlertEngine()
        self._motion = {}
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
        payload = msg.payload.decode("utf-8", errors="replace")
        self.process_payload(device_id, kind, payload)

    def _motion_deviation(self, device_id, now_epoch):
        entry = self._motion.get(device_id)
        if entry is None:
            return None
        recorded_at, deviation = entry
        if now_epoch - recorded_at > 30:
            return None
        return deviation

    def _patient_for(self, device_id):
        binding = db.get_active_binding(device_id)
        if binding is None:
            return None, None
        return db.get_patient(binding["patient_id"]), binding

    def process_payload(self, device_id, kind, payload, ts=None, now=None):
        ts = ts or utc_now()
        now_epoch = time.time() if now is None else now
        now_dt = datetime.fromtimestamp(now_epoch, tz=timezone.utc)
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
        if not isinstance(data, dict):
            return

        if kind == "vitals":
            data["temp"] = self._valid_temp(data.get("temp"))

        patient, _binding = self._patient_for(device_id)

        if kind == "vitals":
            result = anomaly.evaluate_vitals(
                data.get("hr"),
                data.get("spo2"),
                data.get("temp"),
            )
            db.add_vitals(device_id, data, ts)
            if result["level"] != "normal":
                self._maybe_publish_anomaly(self.client, device_id, result, ts)
            if patient is not None:
                motion_g = self._motion_deviation(device_id, now_epoch)
                self.engine.observe_vitals(
                    patient, device_id, data, result, motion_g, now_dt
                )
            self._update_model(
                device_id, now_epoch, data, result["level"], ts, patient, now_dt
            )
        elif kind == "motion":
            db.upsert_device(
                device_id,
                ts,
                status="online",
                activity=data.get("act"),
            )
            ax = data.get("ax") or 0.0
            ay = data.get("ay") or 0.0
            az = data.get("az") or 0.0
            self._motion[device_id] = (
                now_epoch,
                abs((ax * ax + ay * ay + az * az) ** 0.5 - 1.0),
            )
            buffer = self._buffer(device_id)
            if buffer:
                buffer.add_motion(now_epoch, data)
        elif kind == "event":
            event_type = str(data.get("type", "event"))
            db.add_event(device_id, event_type, payload, ts)
            if event_type == "fall":
                db.add_anomaly(device_id, 1.0, "alert", "fall detected", ts)
                db.upsert_device(device_id, ts, status="online", state="fall")
                if patient is not None:
                    self.engine.observe_event(patient, device_id, event_type, now_dt)

    @staticmethod
    def _valid_temp(value):
        if value is None or isinstance(value, bool):
            return None
        try:
            temp = float(value)
        except (TypeError, ValueError):
            return None
        if not config.TEMP_VALID_MIN <= temp <= config.TEMP_VALID_MAX:
            return None
        return temp

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

    def _update_model(self, device_id, now, data, rule_level, ts, patient, now_dt):
        buffer = self._buffer(device_id)
        if buffer is None:
            return
        buffer.add_vitals(now, data)
        result = buffer.update(now, rule_level)
        status = buffer.status()
        baseline = None
        if status.get("ready"):
            rows = [row for row in buffer.vitals if row[1] is not None or row[2] is not None]
            if rows:
                hr_values = [row[1] for row in rows if row[1] is not None]
                spo2_values = [row[2] for row in rows if row[2] is not None]
                temp_values = [row[3] for row in rows if row[3] is not None]
                baseline = {
                    "hr": sum(hr_values) / len(hr_values) if hr_values else None,
                    "spo2": sum(spo2_values) / len(spo2_values) if spo2_values else None,
                    "temp": sum(temp_values) / len(temp_values) if temp_values else None,
                }
        if patient is not None:
            db.upsert_baseline(
                device_id,
                patient["id"],
                status.get("ready", False),
                status.get("calibration_windows", 0),
                config.BASELINE_WINDOWS_REQUIRED,
                hr_baseline=(baseline or {}).get("hr"),
                spo2_baseline=(baseline or {}).get("spo2"),
                temp_baseline=(baseline or {}).get("temp"),
                calibrated_at=ts if status.get("ready") else None,
                stale=not status.get("ready", False),
                now=ts,
            )
            if baseline:
                self.engine.set_baseline(device_id, baseline, now_dt)
            if result and result["level"] != "normal":
                self._maybe_publish_anomaly(self.client, device_id, result, ts)
                self.engine.observe_model(patient, device_id, result, now_dt)
        elif result and result["level"] != "normal":
            self._maybe_publish_anomaly(self.client, device_id, result, ts)

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
