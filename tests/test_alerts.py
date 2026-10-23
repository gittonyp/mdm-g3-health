import unittest
from datetime import datetime, timedelta, timezone

from server import alerts, clinic, config, db
from tests.support import DatabaseTestCase

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

    def test_exact_reason_strings(self):
        self.assertEqual(alerts.classify_vitals({"hr": 39})["reason"], "heart rate 39 bpm")
        self.assertEqual(alerts.classify_vitals({"spo2": 87})["reason"], "SpO2 87%")
        self.assertEqual(
            alerts.classify_vitals({"temp": 39.6})["reason"], "temperature 39.6 C"
        )

    def test_model_and_event_classification(self):
        self.assertEqual(
            alerts.classify_model({"level": "alert", "score": 0.91}),
            {
                "tier": "actionable",
                "kind": "model",
                "score": 0.91,
                "reason": "model alert",
                "value": 0.91,
                "threshold": None,
            },
        )
        self.assertEqual(
            alerts.classify_model({"level": "watch", "score": 0.6})["tier"], "watch"
        )
        self.assertIsNone(alerts.classify_model({"level": "normal", "score": 0.2}))
        self.assertEqual(alerts.classify_event("fall")["tier"], "emergency")
        self.assertEqual(alerts.classify_event("fall")["kind"], "fall")
        self.assertIsNone(alerts.classify_event("button"))


class HelpersTest(unittest.TestCase):
    def test_iso_and_parse_ts(self):
        self.assertEqual(alerts.iso(NOW), "2026-10-22T12:00:00+00:00")
        self.assertEqual(alerts.parse_ts("2026-10-22T12:00:00+00:00"), NOW)
        self.assertEqual(alerts.parse_ts("2026-10-22T12:00:00Z"), NOW)

    def test_owner_for(self):
        self.assertEqual(alerts.owner_for({"caregiver_available": 1}), "caregiver")
        self.assertEqual(alerts.owner_for({"caregiver_available": 0}), "doctor")

    def test_tier_rank(self):
        self.assertLess(alerts.tier_rank("emergency"), alerts.tier_rank("watch"))
        self.assertEqual(alerts.tier_rank("unknown"), 5)
        self.assertEqual(alerts.tier_rank("bogus"), 5)

    def test_build_evidence(self):
        candidate = alerts.classify_vitals({"hr": 125})
        evidence = alerts.build_evidence(
            candidate, {"hr": 125}, {"hr_baseline": 100}, quality="good"
        )
        self.assertEqual(evidence["signal"], "hr")
        self.assertEqual(evidence["value"], 125)
        self.assertEqual(evidence["baseline"], 100)
        self.assertEqual(evidence["delta_pct"], 25.0)
        self.assertEqual(evidence["quality"], "good")
        self.assertEqual(evidence["source"], "rule")
        self.assertIn("duration_s", evidence)
        self.assertIn("windows", evidence)
        self.assertIn("model_score", evidence)

        no_baseline = alerts.build_evidence(candidate, {"hr": 125}, None)
        self.assertIsNone(no_baseline["baseline"])
        self.assertIsNone(no_baseline["delta_pct"])

    def test_trigger_onset_is_first_sample_of_run(self):
        samples = [
            (NOW, "watch"),
            (NOW + timedelta(seconds=10), "actionable"),
            (NOW + timedelta(seconds=20), "actionable"),
        ]
        self.assertEqual(
            alerts.trigger_onset(samples, "actionable"),
            NOW + timedelta(seconds=10),
        )
        self.assertIsNone(alerts.trigger_onset(samples[:1], "actionable"))

    def test_sustained_tracker_reset(self):
        tracker = alerts.SustainedTracker(config.ALERT_BUCKET_SECONDS)
        tracker.record(NOW, "emergency", {"tier": "emergency"})
        tracker.record(NOW + timedelta(seconds=10), "emergency", {"tier": "emergency"})
        self.assertIsNotNone(tracker.sustained(NOW + timedelta(seconds=10), "emergency", 2, 3))
        tracker.reset()
        self.assertIsNone(tracker.sustained(NOW + timedelta(seconds=10), "emergency", 2, 3))


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

    def test_highest_tier_wins_in_a_bucket(self):
        tracker = alerts.SustainedTracker(10.0)
        tracker.record(NOW, "watch", {"tier": "watch"})
        tracker.record(NOW + timedelta(seconds=1), "emergency", {"tier": "emergency"})
        tracker.record(NOW + timedelta(seconds=10), "emergency", {"tier": "emergency"})
        self.assertIsNotNone(
            tracker.sustained(NOW + timedelta(seconds=10), "emergency", 2, 3)
        )


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
        monitor = alerts.AlertMonitor()
        self.assertEqual(monitor.run_once(NOW)["resolved"], 1)