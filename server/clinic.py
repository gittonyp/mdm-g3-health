import sqlite3
from datetime import date, datetime, timedelta, timezone

from . import config, db

VALID_PROGRAMS = {"telehealth", "hospice"}
VALID_SEX = {"F", "M", "O", "U"}
NOTE_KINDS = {"clinical", "caregiver", "visit", "follow_up"}
PATIENT_FIELDS = {
    "display_name",
    "dob",
    "sex",
    "primary_condition",
    "reason_for_monitoring",
    "medications",
    "mobility",
    "goals_of_care",
    "caregiver_name",
    "caregiver_contact",
    "caregiver_available",
    "program",
    "comfort_mode",
    "next_review_at",
    "archived",
}
BOOL_FIELDS = {"caregiver_available", "comfort_mode", "archived"}


class ClinicError(ValueError):
    status_code = 400


class NotFound(ClinicError):
    status_code = 404


class Conflict(ClinicError):
    status_code = 409


class InvalidState(ClinicError):
    status_code = 422


def channel_for_device(device_id):
    device_id = str(device_id).strip()
    if device_id == config.DEFAULT_DEVICE_ID:
        return config.MQTT_ROOT
    return f"{config.MQTT_ROOT}/{device_id}"


def normalize_actor(actor):
    value = str(actor or "doctor").strip().lower()
    if value not in {"doctor", "caregiver"}:
        raise ClinicError("actor must be doctor or caregiver")
    return value


def _parse_datetime(value):
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalize_datetime(value):
    return _parse_datetime(value).isoformat(timespec="seconds")


def _bool_int(value, field):
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return 1 if value else 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return 1
        if normalized in {"0", "false", "no", "off", ""}:
            return 0
    raise ClinicError(f"{field} must be a boolean")


def _required(payload, field):
    if field not in payload or payload[field] is None or str(payload[field]).strip() == "":
        raise ClinicError(f"{field} is required")


def validate_patient_payload(payload, partial=False):
    if not isinstance(payload, dict):
        raise ClinicError("payload must be an object")
    if not partial:
        for field in ("display_name", "dob", "program"):
            _required(payload, field)

    cleaned = {}
    for field, value in payload.items():
        if field not in PATIENT_FIELDS:
            raise ClinicError(f"unknown field: {field}")

        if field == "display_name":
            text = str(value).strip() if value is not None else ""
            if not text:
                raise ClinicError("display_name is required")
            cleaned[field] = text
        elif field == "dob":
            if value is None or str(value).strip() == "":
                raise ClinicError("dob is required")
            try:
                cleaned[field] = date.fromisoformat(str(value)).isoformat()
            except ValueError as exc:
                raise ClinicError("dob must be an ISO date (YYYY-MM-DD)") from exc
        elif field == "sex":
            text = "U" if value is None or str(value).strip() == "" else str(value).strip().upper()
            if text not in VALID_SEX:
                raise ClinicError("sex must be one of F, M, O, U")
            cleaned[field] = text
        elif field == "program":
            text = str(value).strip().lower() if value is not None else ""
            if text not in VALID_PROGRAMS:
                raise ClinicError("program must be telehealth or hospice")
            cleaned[field] = text
        elif field == "next_review_at":
            if value is None:
                cleaned[field] = None
            else:
                try:
                    cleaned[field] = _normalize_datetime(value)
                except ValueError as exc:
                    raise ClinicError("next_review_at must be an ISO 8601 timestamp") from exc
        elif field in BOOL_FIELDS:
            cleaned[field] = _bool_int(value, field)
        else:
            if value is None:
                cleaned[field] = None
            elif isinstance(value, (dict, list, tuple, set)):
                raise ClinicError(f"{field} must be text")
            else:
                cleaned[field] = str(value).strip() or None
    return cleaned


def create_patient(payload, now=None):
    if not isinstance(payload, dict):
        raise ClinicError("payload must be an object")
    data = dict(payload)
    device_id = data.pop("device_id", None)
    if device_id is None or str(device_id).strip() == "":
        raise ClinicError("device_id is required")
    device_id = str(device_id).strip()
    requested_channel = data.pop("channel", None)

    fields = validate_patient_payload(data)
    if db.get_active_binding(device_id) is not None:
        raise Conflict(f"device {device_id} is already bound")
    channel = (
        str(requested_channel).strip()
        if requested_channel is not None and str(requested_channel).strip()
        else channel_for_device(device_id)
    )
    if db.get_active_binding_by_channel(channel) is not None:
        raise Conflict(f"channel {channel} is already in use")

    timestamp = now or db.utc_now()
    fields["created_at"] = timestamp
    fields["updated_at"] = timestamp
    patient = db.insert_patient(fields)
    try:
        db.bind_device(patient["id"], device_id, channel, now=timestamp)
    except sqlite3.IntegrityError as exc:
        raise Conflict(f"device {device_id} is already bound") from exc
    patient["channel"] = channel
    return patient


def update_patient(patient_id, payload, now=None):
    if not isinstance(payload, dict):
        raise ClinicError("payload must be an object")
    if db.get_patient(patient_id) is None:
        raise NotFound(f"patient {patient_id} not found")
    if "id" in payload:
        raise ClinicError("id cannot be updated")
    if "device_id" in payload:
        raise ClinicError("device_id cannot be updated; use bind_device")
    fields = validate_patient_payload(payload, partial=True)
    previous = db.get_patient(patient_id)
    updated = db.update_patient(patient_id, fields, now=now or db.utc_now())
    if updated is None:
        raise NotFound(f"patient {patient_id} not found")
    if (
        previous is not None
        and previous.get("caregiver_available") == 1
        and updated.get("caregiver_available") == 0
    ):
        from . import alerts

        alerts.reassign_caregiver_alerts(patient_id, now=now)
    return updated


def list_patients(include_archived=False, program=None):
    if program is not None and program not in VALID_PROGRAMS:
        raise ClinicError("program must be telehealth or hospice")
    rows = db.list_patients(include_archived=include_archived)
    if program is not None:
        rows = [row for row in rows if row.get("program") == program]
    return rows


def get_patient_detail(patient_id, now=None):
    from . import alerts

    patient = db.get_patient(patient_id)
    if patient is None:
        raise NotFound(f"patient {patient_id} not found")
    binding = db.get_patient_binding(patient_id)
    device_id = binding["device_id"] if binding else None
    latest_vital = db.get_latest_vital(device_id) if device_id else None
    baseline = db.get_baseline(device_id) if device_id else None
    return {
        "patient": patient,
        "device": binding,
        "latest_vital": latest_vital,
        "baseline": baseline,
        "open_alerts": alerts.decorate_alerts(db.get_open_alerts(patient_id), now=now),
        "recent_alerts": alerts.decorate_alerts(
            db.get_recent_alerts(patient_id, limit=20), now=now
        ),
        "notes": db.get_notes(patient_id),
    }


def bind_device(patient_id, device_id, channel=None, now=None):
    if db.get_patient(patient_id) is None:
        raise NotFound(f"patient {patient_id} not found")
    if device_id is None or str(device_id).strip() == "":
        raise ClinicError("device_id is required")
    device_id = str(device_id).strip()
    channel = str(channel).strip() if channel is not None and str(channel).strip() else channel_for_device(device_id)
    existing_device = db.get_active_binding(device_id)
    if existing_device is not None and existing_device["patient_id"] != patient_id:
        raise Conflict(f"device {device_id} is already bound")
    existing_patient = db.get_patient_binding(patient_id)
    if existing_patient is not None and existing_patient["device_id"] != device_id:
        raise Conflict(f"patient {patient_id} already has a bound device")
    existing_channel = db.get_active_binding_by_channel(channel)
    if existing_channel is not None and existing_channel["patient_id"] != patient_id:
        raise Conflict(f"channel {channel} is already in use")
    try:
        return db.bind_device(patient_id, device_id, channel, now=now)
    except sqlite3.IntegrityError as exc:
        raise Conflict(f"device {device_id} is already bound") from exc


def unbind_device(patient_id, device_id, now=None):
    if db.get_patient(patient_id) is None:
        raise NotFound(f"patient {patient_id} not found")
    if not db.unbind_device(patient_id, device_id, now=now):
        raise NotFound(f"device {device_id} is not bound to {patient_id}")


def unassigned_devices():
    return db.get_unassigned_devices()


def add_note(patient_id, author, kind, text, now=None):
    if db.get_patient(patient_id) is None:
        raise NotFound(f"patient {patient_id} not found")
    author = normalize_actor(author)
    if kind not in NOTE_KINDS:
        raise ClinicError("kind must be clinical, caregiver, visit, or follow_up")
    if text is None or str(text).strip() == "":
        raise ClinicError("text is required")
    return db.add_note(patient_id, author, kind, str(text), ts=now)


def list_notes(patient_id):
    if db.get_patient(patient_id) is None:
        raise NotFound(f"patient {patient_id} not found")
    return db.get_notes(patient_id)


def set_follow_up(patient_id, next_review_at, author, note=None, now=None):
    if db.get_patient(patient_id) is None:
        raise NotFound(f"patient {patient_id} not found")
    try:
        normalized = _normalize_datetime(next_review_at)
    except (TypeError, ValueError) as exc:
        raise ClinicError("next_review_at must be an ISO 8601 timestamp") from exc
    actor = normalize_actor(author)

    timestamp = now or db.utc_now()
    updated = db.update_patient(
        patient_id, {"next_review_at": normalized}, now=timestamp
    )
    if note is not None and str(note).strip():
        db.add_note(patient_id, actor, "follow_up", str(note), ts=timestamp)
    return updated


def _window_datetime(value, since, until):
    try:
        parsed = _parse_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed < since or parsed > until:
        return None
    return parsed


def get_trends(patient_id, hours=24, now=None):
    if db.get_patient(patient_id) is None:
        raise NotFound(f"patient {patient_id} not found")
    try:
        hours = int(hours)
    except (TypeError, ValueError) as exc:
        raise ClinicError("hours must be a positive integer") from exc
    if hours <= 0:
        raise ClinicError("hours must be a positive integer")

    now_dt = _parse_datetime(now or db.utc_now())
    since_dt = now_dt - timedelta(hours=hours)
    since = since_dt.isoformat(timespec="seconds")
    bucket_seconds = max(60, int(hours * 3600 / config.CHART_BUCKET_TARGET))

    binding = db.get_patient_binding(patient_id)
    series = []
    baseline = None
    if binding:
        device_id = binding["device_id"]
        buckets = {}
        for row in db.get_vitals_since(device_id, since):
            if _window_datetime(row.get("ts"), since_dt, now_dt) is None:
                continue
            index = int(_parse_datetime(row["ts"]).timestamp() // bucket_seconds)
            bucket = buckets.setdefault(
                index, {"hr": [], "spo2": [], "temp": []}
            )
            for key in ("hr", "spo2", "temp"):
                value = row.get(key)
                if value is not None:
                    bucket[key].append(float(value))
        for index in sorted(buckets):
            bucket = buckets[index]
            series.append(
                {
                    "ts": datetime.fromtimestamp(
                        index * bucket_seconds, tz=timezone.utc
                    ).isoformat(timespec="seconds"),
                    "hr": (
                        sum(bucket["hr"]) / len(bucket["hr"])
                        if bucket["hr"]
                        else None
                    ),
                    "spo2": (
                        sum(bucket["spo2"]) / len(bucket["spo2"])
                        if bucket["spo2"]
                        else None
                    ),
                    "temp": (
                        sum(bucket["temp"]) / len(bucket["temp"])
                        if bucket["temp"]
                        else None
                    ),
                }
            )
        baseline_row = db.get_baseline(device_id)
        if baseline_row is not None:
            baseline = {
                "hr": baseline_row.get("hr_baseline"),
                "spo2": baseline_row.get("spo2_baseline"),
                "temp": baseline_row.get("temp_baseline"),
            }

    markers = []
    for alert in db.get_alerts_since(patient_id, since):
        if _window_datetime(alert.get("created_at"), since_dt, now_dt) is None:
            continue
        markers.append(
            {
                "ts": alert.get("created_at"),
                "type": alert.get("tier"),
                "label": alert.get("reason"),
            }
        )
    for note in db.get_notes(patient_id, limit=1000):
        if _window_datetime(note.get("ts"), since_dt, now_dt) is None:
            continue
        markers.append(
            {
                "ts": note.get("ts"),
                "type": note.get("kind"),
                "label": note.get("text"),
            }
        )
    markers.sort(key=lambda marker: marker.get("ts") or "")

    return {
        "hours": hours,
        "bucket_seconds": bucket_seconds,
        "series": series,
        "baseline": baseline,
        "band_pct": 0.10,
        "markers": markers,
    }


def get_patient_audit(patient_id):
    if db.get_patient(patient_id) is None:
        raise NotFound(f"patient {patient_id} not found")
    rows = db.get_alert_events_for_patient(patient_id)
    rows.extend(db.get_audit_for_patient(patient_id))
    rows.sort(
        key=lambda row: (row.get("ts") or "", row.get("id") or 0), reverse=True
    )
    return rows
