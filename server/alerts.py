from datetime import datetime, timedelta, timezone

from . import config

TIER_RANK = {
    "emergency": 0,
    "actionable": 1,
    "quality": 2,
    "watch": 3,
    "stable": 4,
    "unknown": 5,
}

_TIER_SCORE = {"emergency": 1.0, "actionable": 0.95, "watch": 0.45}

_SUSTAINED_SECONDS = (
    config.EMERGENCY_WINDOW_SECONDS,
    config.MODEL_WINDOW_SECONDS,
    config.ACTIONABLE_WINDOWS * config.ALERT_BUCKET_SECONDS,
    config.WATCH_WINDOWS * config.ALERT_BUCKET_SECONDS,
    config.TREND_SUSTAINED_SECONDS,
)
_RETENTION_SECONDS = max(_SUSTAINED_SECONDS) * 4


def _as_utc(value):
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def iso(dt):
    return _as_utc(dt).isoformat(timespec="seconds")


def parse_ts(value):
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return _as_utc(datetime.fromisoformat(value))


def tier_rank(tier):
    return TIER_RANK.get(tier, TIER_RANK["unknown"])


def owner_for(patient, tier=None):
    if tier in (None, "emergency", "actionable"):
        return "caregiver" if patient.get("caregiver_available") == 1 else "doctor"
    return "doctor"


def due_for(tier, now):
    seconds = config.DUE_SECONDS.get(tier, config.DUE_SECONDS["watch"])
    return iso(now + timedelta(seconds=seconds))


def _usable_vitals(data):
    return (
        data.get("finger") == 1
        and data.get("hr") is not None
        and data.get("spo2") is not None
    )


def classify_quality(data, motion_g):
    if not _usable_vitals(data):
        return None
    if motion_g is None or motion_g < config.MOTION_ARTIFACT_G:
        return None
    return "motion_artifact"


def _reason(kind, value):
    if kind == "hr":
        return f"heart rate {value:.0f} bpm"
    if kind == "spo2":
        return f"SpO2 {value:.0f}%"
    return f"temperature {value:.1f} C"


def _vital_result(tier, kind, value, threshold):
    return {
        "tier": tier,
        "kind": kind,
        "score": _TIER_SCORE[tier],
        "reason": _reason(kind, value),
        "value": value,
        "threshold": threshold,
    }


def _evaluate_signal(kind, value):
    if kind == "hr":
        checks = (
            ("emergency", config.EMERGENCY_HR_LOW, config.EMERGENCY_HR_HIGH),
            ("actionable", config.ACTIONABLE_HR_LOW, config.ACTIONABLE_HR_HIGH),
            ("watch", config.WATCH_HR_LOW, config.WATCH_HR_HIGH),
        )
        for tier, low, high in checks:
            if value < low:
                return _vital_result(tier, kind, value, low)
            if value > high:
                return _vital_result(tier, kind, value, high)
        return None

    if kind == "spo2":
        checks = (
            ("emergency", config.EMERGENCY_SPO2),
            ("actionable", config.ACTIONABLE_SPO2),
            ("watch", config.WATCH_SPO2),
        )
        for tier, threshold in checks:
            if value < threshold:
                return _vital_result(tier, kind, value, threshold)
        return None

    if kind != "temp":
        return None
    checks = (
        ("emergency", config.EMERGENCY_TEMP_LOW, config.EMERGENCY_TEMP_HIGH),
        ("actionable", config.ACTIONABLE_TEMP_LOW, config.ACTIONABLE_TEMP_HIGH),
        ("watch", config.WATCH_TEMP_LOW, config.WATCH_TEMP_HIGH),
    )
    for tier, low, high in checks:
        if value < low:
            return _vital_result(tier, kind, value, low)
        if (tier == "watch" and value > high) or (tier != "watch" and value >= high):
            return _vital_result(tier, kind, value, high)
    return None


def classify_vitals(data):
    best = None
    for kind in ("hr", "spo2", "temp"):
        value = data.get(kind)
        if value is None:
            continue
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        result = _evaluate_signal(kind, numeric)
        if result is None:
            continue
        if best is None or tier_rank(result["tier"]) < tier_rank(best["tier"]):
            best = result
    return best


def classify_model(result):
    level = result.get("level")
    if level == "alert":
        tier = "actionable"
    elif level == "watch":
        tier = "watch"
    else:
        return None
    score = result.get("score")
    return {
        "tier": tier,
        "kind": "model",
        "score": score,
        "reason": result.get("reason") or f"model {level}",
        "value": score,
        "threshold": None,
    }


def classify_event(event_type):
    if event_type != "fall":
        return None
    return {
        "tier": "emergency",
        "kind": "fall",
        "score": 1.0,
        "reason": "fall detected",
        "value": None,
        "threshold": None,
    }


def _baseline_value(baseline, kind):
    if not baseline:
        return None
    for key in (kind, f"{kind}_baseline"):
        if baseline.get(key) is not None:
            return baseline[key]
    return None


def _window_shape(tier, kind):
    if kind == "model":
        return {
            "required": config.MODEL_WINDOWS_REQUIRED,
            "of": config.MODEL_WINDOWS,
        }
    if tier == "emergency":
        return {
            "required": config.EMERGENCY_CONFIRMATIONS,
            "of": max(
                1,
                int(round(config.EMERGENCY_WINDOW_SECONDS / config.ALERT_BUCKET_SECONDS)),
            ),
        }
    if tier == "actionable":
        return {
            "required": config.ACTIONABLE_WINDOWS_REQUIRED,
            "of": config.ACTIONABLE_WINDOWS,
        }
    if tier == "watch":
        return {
            "required": config.WATCH_WINDOWS_REQUIRED,
            "of": config.WATCH_WINDOWS,
        }
    return {}


def build_evidence(candidate, data, baseline, quality="good"):
    kind = candidate.get("kind")
    value = candidate.get("value")
    if value is None:
        value = data.get(kind)

    baseline_value = _baseline_value(baseline, kind)
    delta_pct = None
    if baseline_value not in (None, 0) and value is not None:
        delta_pct = round((value - baseline_value) / abs(baseline_value) * 100, 1)

    tier = candidate.get("tier")
    window_shape = _window_shape(tier, kind)
    windows = candidate.get("windows")
    if isinstance(windows, dict):
        window_count = windows.get("of", window_shape.get("of", 0))
    elif windows is not None:
        window_count = int(windows)
    else:
        window_count = window_shape.get("of", 0)
    duration_s = candidate.get("duration_s")
    if duration_s is None:
        window_seconds = (
            config.MODEL_WINDOW_SECONDS
            if kind == "model"
            else config.ALERT_BUCKET_SECONDS
        )
        duration_s = (window_count or 0) * window_seconds

    source = candidate.get("source")
    if source is None:
        if kind == "model":
            source = "model"
        elif kind == "fall":
            source = "event"
        elif tier == "quality":
            source = "quality"
        else:
            source = "rule"

    model_score = candidate.get("model_score")
    if model_score is None and source == "model":
        model_score = candidate.get("score", data.get("score"))

    return {
        "signal": kind,
        "value": value,
        "baseline": baseline_value,
        "delta_pct": delta_pct,
        "duration_s": duration_s,
        "windows": window_count,
        "quality": quality,
        "source": source,
        "model_score": model_score,
    }


def _sample_parts(sample):
    if isinstance(sample, dict):
        timestamp = sample.get("ts", sample.get("timestamp"))
        sample_tier = sample.get("tier")
    else:
        timestamp, sample_tier = sample
    if isinstance(timestamp, str):
        timestamp = parse_ts(timestamp)
    return _as_utc(timestamp), sample_tier


def trigger_onset(samples, tier):
    onset = None
    rank = tier_rank(tier)
    for sample in reversed(list(samples)):
        timestamp, sample_tier = _sample_parts(sample)
        if tier_rank(sample_tier) <= rank:
            onset = timestamp
        else:
            break
    return onset


class SustainedTracker:
    def __init__(self, bucket_seconds):
        self.bucket_seconds = float(bucket_seconds)
        self.buckets = {}

    def _bucket(self, now):
        return int(_as_utc(now).timestamp() // self.bucket_seconds)

    def _prune(self, now):
        cutoff = int((_as_utc(now).timestamp() - _RETENTION_SECONDS) // self.bucket_seconds)
        for bucket in [key for key in self.buckets if key < cutoff]:
            del self.buckets[bucket]

    def record(self, now, tier, candidate=None):
        bucket = self._bucket(now)
        current = self.buckets.get(bucket)
        if current is None or tier_rank(tier) <= tier_rank(current["tier"]):
            if candidate is None and current is not None:
                candidate = current["candidate"]
            self.buckets[bucket] = {"tier": tier, "candidate": candidate}
        self._prune(now)

    def sustained(self, now, tier, required, of):
        rank = tier_rank(tier)
        current = self._bucket(now)
        count = 0
        newest = None
        for bucket in range(current - of + 1, current + 1):
            entry = self.buckets.get(bucket)
            if entry is None:
                continue
            if tier_rank(entry["tier"]) > rank:
                continue
            count += 1
            if entry["candidate"] is not None:
                newest = entry["candidate"]
        if count < required:
            return None
        return newest

    def reset(self):
        self.buckets.clear()


# --- Alert lifecycle (Task 4) ---

_CARE_INSTRUCTION = {
    "offline": "Check device power and WiFi",
    "no_finger": "Place a finger on the sensor",
    "stale": "Check the device is running",
    "motion_artifact": "Ask the patient to sit still and recheck",
    "hr": "Check the patient and recheck the reading",
    "spo2": "Check the patient and recheck the reading",
    "temp": "Check the patient and recheck the reading",
    "fall": "Check on the patient now",
    "model": "Check the patient and review the trend",
}

_NEXT_ACTION = {
    "emergency": "Call caregiver now",
    "actionable": "Caregiver check, then doctor review",
    "quality": "Restore sensor",
    "watch": "Review trend",
    "stable": "Next review",
}


def _now(now=None):
    if now is None:
        from . import db

        return parse_ts(db.utc_now())
    if isinstance(now, str):
        return parse_ts(now)
    return _as_utc(now)


def _evidence_dict(alert):
    import json

    value = alert.get("evidence_json")
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return {}


def next_action(tier, patient=None):
    if tier == "emergency" and patient and patient.get("comfort_mode") == 1:
        return "Follow the comfort plan; call caregiver now"
    return _NEXT_ACTION.get(tier, _NEXT_ACTION["watch"])


def care_instruction(alert):
    return _CARE_INSTRUCTION.get(alert.get("kind"), "Check the patient and recheck")


def display_status(alert, now):
    from . import clinic

    status = alert.get("status")
    if status == "resolved":
        return "Resolved"
    due_at = alert.get("due_at")
    if due_at and parse_ts(due_at) <= now:
        return "Overdue"
    if status == "acknowledged":
        return f"Acknowledged by {alert.get('acknowledged_by') or 'doctor'}"
    response = alert.get("caregiver_response")
    if alert.get("owner") == "caregiver":
        if response == "done":
            return "Caregiver done - doctor review"
        return "Awaiting caregiver"
    if response in ("cannot", "contact_doctor"):
        return "Needs doctor review"
    return "Needs doctor review"


def decorate_alert(alert, now=None):
    current = _now(now)
    decorated = dict(alert)
    created = alert.get("created_at")
    age_s = 0
    if created:
        try:
            age_s = max(0, int((current - parse_ts(created)).total_seconds()))
        except (TypeError, ValueError):
            age_s = 0
    decorated["age_s"] = age_s
    decorated["overdue"] = display_status(alert, current) == "Overdue"
    decorated["display_status"] = display_status(alert, current)
    decorated["next_action"] = next_action(alert.get("tier"), None)
    decorated["care_instruction"] = care_instruction(alert)
    decorated["evidence"] = _evidence_dict(alert)
    return decorated


def decorate_alerts(rows, now=None):
    return [decorate_alert(row, now=now) for row in rows]


def raise_alert(
    patient,
    device_id,
    tier,
    kind,
    source,
    reason,
    evidence,
    score=None,
    now=None,
):
    import json

    from . import clinic, db

    current = _now(now)
    timestamp = iso(current)
    dedupe_key = f"{patient['id']}:{kind}:{tier}"

    existing = db.get_open_alert_by_key(dedupe_key)
    if existing is not None:
        db.update_alert(
            existing["id"],
            {
                "reason": reason,
                "evidence_json": json.dumps(evidence or {}),
                "score": score if score is not None else existing.get("score"),
                "last_seen_at": timestamp,
                "updated_at": timestamp,
            },
        )
        return existing["id"]

    if patient.get("comfort_mode") == 1 and tier == "watch":
        db.add_audit(
            "system",
            "patient",
            patient["id"],
            "comfort_suppressed",
            {"kind": kind},
            ts=timestamp,
        )
        return None

    other = db.get_open_alert_by_kind(patient["id"], kind)
    if other is not None and other.get("tier") != tier:
        db.update_alert(
            other["id"],
            {
                "status": "resolved",
                "resolved_at": timestamp,
                "resolved_by": "system",
                "resolution_note": f"superseded by {tier}",
            },
        )
        db.add_alert_event(
            other["id"], "system", "resolved", f"superseded by {tier}", now=timestamp
        )

    if tier == "watch" and db.count_open_alerts(patient["id"]) >= config.OPEN_ALERT_CAP:
        db.add_audit(
            "system",
            "patient",
            patient["id"],
            "alert_suppressed",
            {"kind": kind, "tier": tier},
            ts=timestamp,
        )
        return None

    alert_id = db.create_alert(
        {
            "patient_id": patient["id"],
            "device_id": device_id,
            "tier": tier,
            "kind": kind,
            "source": source,
            "status": "open",
            "owner": owner_for(patient, tier),
            "score": score,
            "reason": reason,
            "evidence_json": json.dumps(evidence or {}),
            "dedupe_key": dedupe_key,
            "created_at": timestamp,
            "updated_at": timestamp,
            "last_seen_at": timestamp,
            "due_at": due_for(tier, current),
        }
    )
    db.add_alert_event(alert_id, "system", "created", reason, now=timestamp)
    return alert_id


def acknowledge_alert(alert_id, actor, now=None):
    from . import clinic, db

    actor = clinic.normalize_actor(actor)
    if actor != "doctor":
        raise clinic.InvalidState("only a doctor can acknowledge an alert")
    current = _now(now)
    alert = db.get_alert(alert_id)
    if alert is None:
        raise clinic.NotFound(f"alert {alert_id} not found")
    if alert["status"] == "resolved":
        raise clinic.InvalidState("resolved alerts cannot be acknowledged")
    db.update_alert(
        alert_id,
        {
            "status": "acknowledged",
            "acknowledged_at": iso(current),
            "acknowledged_by": actor,
            "updated_at": iso(current),
        },
    )
    db.add_alert_event(alert_id, actor, "acknowledged", now=iso(current))
    return db.get_alert(alert_id)


def resolve_alert(alert_id, actor, note, now=None):
    from . import clinic, db

    actor = clinic.normalize_actor(actor)
    if actor != "doctor":
        raise clinic.InvalidState("only a doctor can resolve an alert")
    if note is None or str(note).strip() == "":
        raise clinic.InvalidState("a resolution note is required")
    current = _now(now)
    alert = db.get_alert(alert_id)
    if alert is None:
        raise clinic.NotFound(f"alert {alert_id} not found")
    if alert["status"] == "resolved":
        raise clinic.InvalidState("alert is already resolved")
    db.update_alert(
        alert_id,
        {
            "status": "resolved",
            "resolved_at": iso(current),
            "resolved_by": actor,
            "resolution_note": str(note).strip(),
            "updated_at": iso(current),
        },
    )
    db.add_alert_event(alert_id, actor, "resolved", str(note).strip(), now=iso(current))
    return db.get_alert(alert_id)


def caregiver_respond(alert_id, actor, response, now=None):
    from . import clinic, db

    actor = clinic.normalize_actor(actor)
    if actor != "caregiver":
        raise clinic.InvalidState("only a caregiver can respond")
    if response not in {"done", "cannot", "contact_doctor"}:
        raise clinic.InvalidState("response must be done, cannot, or contact_doctor")
    current = _now(now)
    alert = db.get_alert(alert_id)
    if alert is None:
        raise clinic.NotFound(f"alert {alert_id} not found")
    if alert["status"] == "resolved":
        raise clinic.InvalidState("resolved alerts cannot be responded to")
    if alert.get("owner") != "caregiver":
        raise clinic.InvalidState("this alert is not caregiver-owned")
    fields = {
        "caregiver_response": response,
        "updated_at": iso(current),
    }
    if response != "done":
        fields["owner"] = "doctor"
        fields["due_at"] = iso(current + timedelta(seconds=600))
    db.update_alert(alert_id, fields)
    db.add_alert_event(alert_id, actor, f"caregiver_{response}", now=iso(current))
    return db.get_alert(alert_id)


def reassign_caregiver_alerts(patient_id, now=None):
    from . import db

    current = _now(now)
    moved = 0
    for alert in db.get_open_alerts(patient_id):
        if alert.get("owner") != "caregiver" or alert.get("caregiver_response") == "done":
            continue
        db.update_alert(
            alert["id"],
            {
                "owner": "doctor",
                "due_at": iso(current + timedelta(seconds=600)),
                "updated_at": iso(current),
            },
        )
        db.add_alert_event(alert["id"], "system", "reassigned", now=iso(current))
        moved += 1
    return moved


def resolve_quality_for_device(device_id, kind, note, now=None):
    from . import db

    if device_id is None:
        return 0
    current = _now(now)
    resolved = 0
    with db.session() as conn:
        rows = conn.execute(
            """
            SELECT * FROM alerts
            WHERE device_id = ? AND tier = 'quality' AND status != 'resolved'
            ORDER BY id
            """,
            (device_id,),
        ).fetchall()
    for row in rows:
        alert = dict(row)
        if kind is not None and alert.get("kind") != kind:
            continue
        db.update_alert(
            alert["id"],
            {
                "status": "resolved",
                "resolved_at": iso(current),
                "resolved_by": "system",
                "resolution_note": note,
                "updated_at": iso(current),
            },
        )
        db.add_alert_event(alert["id"], "system", "resolved", note, now=iso(current))
        resolved += 1
    return resolved


# --- Worklist (Task 5) ---

_WORKLIST_BUCKET = {
    "emergency": 0,
    "actionable": 1,
    "quality": 2,
    "watch": 3,
    "unknown": 4,
    "stable": 5,
}


def _vital_age(latest_vital, now):
    if not latest_vital or not latest_vital.get("ts"):
        return None
    try:
        return (now - parse_ts(latest_vital["ts"])).total_seconds()
    except (TypeError, ValueError):
        return None


def patient_is_unknown(binding, device, latest_vital, now):
    if binding is None or device is None or latest_vital is None:
        return True
    if device.get("status") != "online":
        return True
    age = _vital_age(latest_vital, now)
    if age is None or age > config.STALE_SECONDS:
        return True
    if latest_vital.get("finger") == 0:
        return True
    return False


def _data_quality(binding, device, latest_vital, open_alerts, now):
    if binding is None or device is None:
        return "missing"
    if device.get("status") != "online":
        return "offline"
    if latest_vital is None:
        return "stale"
    age = _vital_age(latest_vital, now)
    if age is None or age > config.STALE_SECONDS:
        return "stale"
    if latest_vital.get("finger") == 0:
        return "no_finger"
    if any(row.get("kind") == "motion_artifact" for row in open_alerts):
        return "motion"
    return "good"


def worklist_sort_key(item):
    tier = item.get("tier") or "stable"
    overdue = bool(item.get("overdue"))
    status = item.get("display_status") or ""
    bucket = _WORKLIST_BUCKET.get(tier, _WORKLIST_BUCKET["stable"])
    if overdue and tier == "emergency":
        bucket = 0
    elif overdue and tier == "actionable":
        bucket = 1
    elif tier in ("emergency", "actionable"):
        if status.startswith("Acknowledged") or status.startswith("Caregiver"):
            bucket = 4
        elif tier == "emergency":
            bucket = 2
        else:
            bucket = 3
    age = item.get("oldest_open_age_s")
    age_key = -(age if age is not None else -1)
    return (bucket, age_key, (item.get("display_name") or "").lower())


def worklist_item(patient, binding, device, open_alerts, latest_vital, baseline, now):
    decorated = decorate_alerts(open_alerts, now=now)
    worst = None
    for alert in decorated:
        if worst is None or tier_rank(alert["tier"]) < tier_rank(worst["tier"]):
            worst = alert
    if worst is not None:
        tier = worst["tier"]
    elif patient_is_unknown(binding, device, latest_vital, now):
        tier = "unknown"
    else:
        tier = "stable"

    oldest_age = None
    for alert in decorated:
        age = alert.get("age_s")
        if age is not None and (oldest_age is None or age > oldest_age):
            oldest_age = age

    if worst is not None:
        what_changed = worst.get("reason")
    elif tier == "unknown":
        what_changed = "No data yet"
    else:
        what_changed = "No change since last review"

    if worst is not None:
        owner = worst.get("owner") or "doctor"
        status = worst.get("display_status")
        overdue = bool(worst.get("overdue"))
    else:
        owner = "doctor"
        status = "Stable" if tier == "stable" else "Unknown"
        overdue = False

    if tier == "stable":
        if patient.get("next_review_at"):
            action = f"Next review {patient['next_review_at']}"
        else:
            action = "Next review unscheduled"
    else:
        action = next_action(tier, patient)

    return {
        "patient_id": patient["id"],
        "display_name": patient.get("display_name"),
        "program": patient.get("program"),
        "tier": tier,
        "what_changed": what_changed,
        "data_quality": _data_quality(binding, device, latest_vital, decorated, now),
        "owner": owner,
        "status": status,
        "display_status": status,
        "age_s": oldest_age,
        "oldest_open_age_s": oldest_age,
        "overdue": overdue,
        "next_action": action,
        "latest_vital": latest_vital,
        "baseline": baseline,
        "open_alerts": decorated,
    }


def get_worklist(broker_connected, now=None):
    from . import db

    current = _now(now)
    items = []
    for patient in db.list_patients(include_archived=False):
        binding = db.get_patient_binding(patient["id"])
        device_id = binding["device_id"] if binding else None
        device = db.get_device(device_id) if device_id else None
        latest_vital = db.get_latest_vital(device_id) if device_id else None
        baseline = db.get_baseline(device_id) if device_id else None
        open_alerts = db.get_open_alerts(patient["id"])
        items.append(
            worklist_item(
                patient, binding, device, open_alerts, latest_vital, baseline, current
            )
        )
    items.sort(key=worklist_sort_key)
    counts = {
        "patients": len(items),
        "need_action": sum(
            1
            for item in items
            if item["overdue"]
            or item["tier"] in ("quality", "actionable", "emergency")
        ),
        "overdue": sum(1 for item in items if item["overdue"]),
        "unknown": sum(1 for item in items if item["tier"] == "unknown"),
    }
    return {
        "generated_at": iso(current),
        "broker_connected": bool(broker_connected),
        "counts": counts,
        "patients": items,
    }


# --- Quality monitor (Task 6) ---

def quality_tasks(binding, device, latest_vital, last_finger_positive, now):
    tasks = {}
    if device is None or device.get("status") != "online":
        tasks["offline"] = "device is offline"
        return tasks
    age = _vital_age(latest_vital, now)
    if latest_vital is None or age is None or age > config.STALE_SECONDS:
        tasks["stale"] = "no recent readings"
        return tasks
    if latest_vital.get("finger") == 0:
        reference = last_finger_positive or latest_vital.get("ts")
        gap = None
        if reference:
            try:
                gap = (now - parse_ts(reference)).total_seconds()
            except (TypeError, ValueError):
                gap = None
        if gap is None or gap > config.NO_FINGER_SECONDS:
            tasks["no_finger"] = "no finger detected"
    return tasks


class AlertMonitor:
    def __init__(self, interval=None):
        self.interval = (
            config.MONITOR_INTERVAL_SECONDS if interval is None else float(interval)
        )
        self._stop = None
        self._thread = None

    def run_once(self, now=None):
        import logging

        from . import db

        current = _now(now)
        created = 0
        resolved = 0
        for binding in db.list_active_bindings():
            try:
                patient = db.get_patient(binding["patient_id"])
                if patient is None or patient.get("archived"):
                    continue
                device_id = binding["device_id"]
                device = db.get_device(device_id)
                latest = db.get_latest_vital(device_id)
                last_fp = db.get_last_finger_positive(device_id)
                tasks = quality_tasks(binding, device, latest, last_fp, current)
                for kind, reason in tasks.items():
                    if raise_alert(
                        patient,
                        device_id,
                        "quality",
                        kind,
                        "quality",
                        reason,
                        {"signal": kind},
                        now=current,
                    ):
                        created += 1
                if not tasks and latest is not None and latest.get("finger") == 1:
                    resolved += resolve_quality_for_device(
                        device_id, None, "condition cleared", now=current
                    )
            except Exception:  # pragma: no cover - defensive monitor loop
                logging.exception("quality monitor failed for %s", binding)
        return {"created": created, "resolved": resolved}

    def start(self):
        import threading

        if self._thread is not None:
            return
        self._stop = threading.Event()

        def loop():
            while not self._stop.wait(self.interval):
                try:
                    self.run_once()
                except Exception:  # pragma: no cover - defensive monitor loop
                    import logging

                    logging.exception("quality monitor loop failed")

        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()

    def stop(self):
        if self._stop is not None:
            self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._thread = None
        self._stop = None


# --- Ingest alert engine (Task 7) ---

class AlertEngine:
    def __init__(self):
        self.trackers = {}
        self.model_tracker = SustainedTracker(config.MODEL_WINDOW_SECONDS)
        self.baselines = {}
        self.baseline_set_at = {}
        self.trend = {}

    def _tracker(self, device_id):
        tracker = self.trackers.get(device_id)
        if tracker is None:
            tracker = SustainedTracker(config.ALERT_BUCKET_SECONDS)
            self.trackers[device_id] = tracker
        return tracker

    def set_baseline(self, device_id, baseline, now):
        current = self.baselines.get(device_id)
        normalized = {
            key: baseline.get(key)
            for key in ("hr", "spo2", "temp")
            if baseline.get(key) is not None
        }
        if not normalized:
            return
        if current != normalized:
            self.baselines[device_id] = normalized
            self.baseline_set_at[device_id] = now
            self.trend.pop(device_id, None)

    def reset(self, device_id):
        self.trackers.pop(device_id, None)
        self.baselines.pop(device_id, None)
        self.baseline_set_at.pop(device_id, None)
        self.trend.pop(device_id, None)

    def _raise_from_candidate(self, patient, device_id, candidate, data, now):
        evidence = build_evidence(
            candidate,
            data,
            self.baselines.get(device_id),
        )
        return raise_alert(
            patient,
            device_id,
            candidate["tier"],
            candidate["kind"],
            evidence.get("source", "rule"),
            candidate.get("reason") or candidate["kind"],
            evidence,
            score=candidate.get("score"),
            now=now,
        )

    def observe_vitals(self, patient, device_id, data, rule_result, motion_g, now):
        current = _now(now)
        usable = (
            data.get("finger") == 1
            and data.get("hr") is not None
            and data.get("spo2") is not None
        )
        if not usable:
            return []
        tracker = self._tracker(device_id)
        if motion_g is not None and motion_g >= config.MOTION_ARTIFACT_G:
            tracker.record(current, "quality", {"tier": "quality", "kind": "motion_artifact", "reason": "motion artifact"})
            return [
                raise_alert(
                    patient,
                    device_id,
                    "quality",
                    "motion_artifact",
                    "quality",
                    "motion artifact",
                    {"signal": "motion_artifact", "motion_g": motion_g},
                    now=current,
                )
            ]
        resolve_quality_for_device(device_id, "motion_artifact", "condition cleared", now=current)

        candidate = classify_vitals(data)
        tier = candidate["tier"] if candidate else "stable"
        tracker.record(current, tier, candidate)
        alerts_raised = []
        emergency = tracker.sustained(current, "emergency", config.EMERGENCY_CONFIRMATIONS, 3)
        actionable = tracker.sustained(
            current, "actionable", config.ACTIONABLE_WINDOWS_REQUIRED, config.ACTIONABLE_WINDOWS
        )
        watch = tracker.sustained(
            current, "watch", config.WATCH_WINDOWS_REQUIRED, config.WATCH_WINDOWS
        )
        chosen = emergency or actionable or watch
        if chosen is not None:
            alert_id = self._raise_from_candidate(patient, device_id, chosen, data, current)
            if alert_id:
                alerts_raised.append(alert_id)

        baseline = self.baselines.get(device_id)
        set_at = self.baseline_set_at.get(device_id)
        if baseline and set_at is not None:
            elapsed = (current - set_at).total_seconds()
            if elapsed >= config.TREND_SUSTAINED_SECONDS:
                for key in ("hr", "spo2", "temp"):
                    base = baseline.get(key)
                    value = data.get(key)
                    if base in (None, 0) or value is None:
                        continue
                    delta = abs(value - base) / abs(base)
                    if delta >= config.TREND_DELTA_PCT:
                        trend_candidate = {
                            "tier": "watch",
                            "kind": key,
                            "score": 0.4,
                            "reason": f"{key} trend {delta * 100:.0f}% from baseline",
                            "value": value,
                            "threshold": base,
                        }
                        alert_id = self._raise_from_candidate(
                            patient, device_id, trend_candidate, data, current
                        )
                        if alert_id:
                            alerts_raised.append(alert_id)
                        break
        return alerts_raised

    def observe_model(self, patient, device_id, result, now):
        current = _now(now)
        candidate = classify_model(result)
        if candidate is None:
            return []
        self.model_tracker.record(current, candidate["tier"], candidate)
        confirmed = self.model_tracker.sustained(
            current,
            candidate["tier"],
            config.MODEL_WINDOWS_REQUIRED,
            config.MODEL_WINDOWS,
        )
        if confirmed is None:
            return []
        alert_id = self._raise_from_candidate(patient, device_id, confirmed, {}, current)
        return [alert_id] if alert_id else []

    def observe_event(self, patient, device_id, event_type, now):
        candidate = classify_event(event_type)
        if candidate is None:
            return []
        current = _now(now)
        alert_id = self._raise_from_candidate(patient, device_id, candidate, {}, current)
        return [alert_id] if alert_id else []
