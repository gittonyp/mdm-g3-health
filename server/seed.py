"""Create the deterministic patients used by the local demo."""

from . import clinic, config, db


def seed():
    db.init_db()
    if db.get_patient("PT-0001") is None:
        clinic.create_patient(
            {
                "display_name": "Demo Patient A",
                "dob": "1940-01-01",
                "program": "hospice",
                "primary_condition": "Demo monitoring",
                "reason_for_monitoring": "Home vital monitoring",
                "goals_of_care": "Comfort-focused review",
                "caregiver_name": "Demo Caregiver",
                "caregiver_available": 1,
                "device_id": "sim01",
            }
        )
    if db.get_patient("PT-0002") is None:
        clinic.create_patient(
            {
                "display_name": "Demo Patient B",
                "dob": "1952-06-15",
                "program": "telehealth",
                "reason_for_monitoring": "Routine follow-up",
                "device_id": "sim02",
            }
        )
    if db.get_patient("PT-0003") is None:
        # The real ESP32 publishes flat topics, which the server records as this device.
        clinic.create_patient(
            {
                "display_name": "ESP32 Board",
                "dob": "1990-01-01",
                "program": "telehealth",
                "reason_for_monitoring": "Real hardware node",
                "device_id": config.DEFAULT_DEVICE_ID,
            }
        )
    return db.list_patients()


if __name__ == "__main__":
    for patient in seed():
        print(f"{patient['id']}: {patient['display_name']}")
