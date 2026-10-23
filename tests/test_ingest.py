import json
import unittest
from datetime import datetime, timedelta, timezone

from server import alerts, clinic, config, db
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
            "sim01", "vitals", payload, alerts.iso(NOW + timedelta(seconds=10)), NOW.timestamp() + 10
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

    def test_floating_temp_pin_is_ignored_not_alerted(self):
        patient = clinic.create_patient(
            {"display_name": "A", "dob": "1940-01-01", "program": "hospice", "device_id": "esp32"}
        )
        for offset in (0, 10, 20):
            payload = json.dumps({"hr": 75, "spo2": 98, "temp": 0.0, "finger": 1})
            self.ingestor.process_payload(
                "esp32", "vitals", payload, alerts.iso(NOW + timedelta(seconds=offset)), NOW.timestamp() + offset
            )
        self.assertEqual(db.get_open_alerts(patient["id"]), [])
        self.assertIsNone(db.get_vitals("esp32", 1)[0]["temp"])

    def test_realistic_esp32_payload_without_temp_is_accepted(self):
        # Current firmware: flat topic, no temp field, hr/spo2/hrv as ints.
        patient = clinic.create_patient(
            {"display_name": "A", "dob": "1940-01-01", "program": "hospice", "device_id": "esp32"}
        )
        payload = '{"t":1234,"hr":72,"spo2":98,"hrv":40,"finger":1,"state":"normal"}'
        self.ingestor.process_payload("esp32", "vitals", payload, alerts.iso(NOW), NOW.timestamp())
        self.assertEqual(db.get_open_alerts(patient["id"]), [])
        row = db.get_vitals("esp32", 1)[0]
        self.assertEqual(row["hr"], 72)
        self.assertIsNone(row["temp"])

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
            "sim01", "vitals", payload, alerts.iso(NOW + timedelta(seconds=10)), NOW.timestamp() + 10
        )
        tiers = {row["tier"] for row in db.get_open_alerts(patient["id"])}
        self.assertNotIn("actionable", tiers)
        self.assertIn("quality", tiers)
