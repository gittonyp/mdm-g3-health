import sqlite3
import unittest

from server import clinic, db
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
