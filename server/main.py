import csv
import io
import sqlite3
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import alerts, clinic, config, db
from .mqtt_ingest import MqttIngestor

ingestor = MqttIngestor()
monitor = alerts.AlertMonitor()


@asynccontextmanager
async def lifespan(app):
    db.init_db()
    db.mark_baselines_stale()
    ingestor.start()
    monitor.start()
    yield
    monitor.stop()
    ingestor.stop()


app = FastAPI(title="MDM G3 Health API", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=config.ROOT_DIR / "server" / "static"), name="static")


@app.exception_handler(clinic.ClinicError)
async def clinic_error_handler(request: Request, exc: clinic.ClinicError):
    return JSONResponse({"detail": str(exc)}, status_code=exc.status_code)


@app.exception_handler(sqlite3.Error)
async def sqlite_error_handler(request: Request, exc: sqlite3.Error):
    return JSONResponse({"detail": "database unavailable"}, status_code=503)


@app.get("/", include_in_schema=False)
def dashboard():
    return RedirectResponse("/clinic", status_code=307)


@app.get("/clinic", include_in_schema=False)
def clinic_page():
    return FileResponse(config.ROOT_DIR / "server" / "static" / "clinic.html")


@app.get("/clinic/patient/{patient_id}", include_in_schema=False)
def patient_page(patient_id: str):
    return FileResponse(config.ROOT_DIR / "server" / "static" / "patient.html")


@app.get("/care", include_in_schema=False)
def care_page():
    return FileResponse(config.ROOT_DIR / "server" / "static" / "care.html")


@app.get("/live", include_in_schema=False)
def live_page():
    return FileResponse(config.ROOT_DIR / "health_dashboard.html")


@app.get("/history", include_in_schema=False)
def history():
    return FileResponse(config.ROOT_DIR / "server" / "static" / "history.html")


def actor(x_demo_actor: str | None = Header(default=None)) -> str:
    return clinic.normalize_actor(x_demo_actor)


def json_result(value):
    response = JSONResponse(value)
    response.headers["cache-control"] = "no-store"
    return response


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "mqtt_connected": ingestor.connected,
        "broker": f"{config.MQTT_HOST}:{config.MQTT_PORT}",
        "root": config.MQTT_ROOT,
        "default_device_id": config.DEFAULT_DEVICE_ID,
        "db": str(config.DB_PATH),
    }


@app.get("/api/config")
def app_config():
    return {
        "root": config.MQTT_ROOT,
        "default_device_id": config.DEFAULT_DEVICE_ID,
        "broker": f"{config.MQTT_HOST}:{config.MQTT_PORT}",
    }


@app.get("/api/stats")
def stats():
    return db.get_stats()


@app.get("/api/devices")
def devices():
    return db.get_devices()


@app.get("/api/vitals")
def vitals(
    device_id: str | None = None,
    limit: int = Query(200, ge=1, le=2000),
):
    return db.get_vitals(device_id, limit)


@app.get("/api/messages")
def messages(
    device_id: str | None = None,
    limit: int = Query(200, ge=1, le=2000),
):
    return db.get_messages(device_id, limit)


@app.get("/api/events")
def events(
    device_id: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
):
    return db.get_events(device_id, limit)


@app.get("/api/anomalies")
def anomalies(
    device_id: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
):
    return db.get_anomalies(device_id, limit)


@app.get("/api/model")
def model_status():
    return ingestor.model_status()


@app.get("/api/clinic/worklist")
def clinic_worklist():
    return json_result(alerts.get_worklist(ingestor.connected))


@app.get("/api/patients")
def patients(
    program: str | None = None,
    include_archived: bool = False,
):
    return json_result(clinic.list_patients(include_archived, program))


@app.post("/api/patients")
def create_patient(payload: dict):
    return json_result(clinic.create_patient(payload))


@app.get("/api/patients/{patient_id}")
def patient_detail(patient_id: str):
    return json_result(clinic.get_patient_detail(patient_id))


@app.patch("/api/patients/{patient_id}")
def update_patient(patient_id: str, payload: dict):
    return json_result(clinic.update_patient(patient_id, payload))


@app.post("/api/patients/{patient_id}/devices")
def bind_patient_device(patient_id: str, payload: dict):
    if not isinstance(payload, dict) or not payload.get("device_id"):
        raise clinic.ClinicError("device_id is required")
    return json_result(
        clinic.bind_device(patient_id, payload["device_id"], payload.get("channel"))
    )


@app.delete("/api/patients/{patient_id}/devices/{device_id}")
def unbind_patient_device(patient_id: str, device_id: str):
    clinic.unbind_device(patient_id, device_id)
    return json_result({"ok": True})


@app.get("/api/patients/{patient_id}/trends")
def patient_trends(patient_id: str, hours: int = Query(24, ge=1, le=720)):
    return json_result(clinic.get_trends(patient_id, hours))


@app.get("/api/patients/{patient_id}/alerts")
def patient_alerts(patient_id: str, status: str | None = None):
    if db.get_patient(patient_id) is None:
        raise clinic.NotFound(f"patient {patient_id} not found")
    rows = db.get_open_alerts(patient_id) if status == "open" else db.get_recent_alerts(patient_id)
    return json_result(alerts.decorate_alerts(rows))


@app.post("/api/alerts/{alert_id}/ack")
def acknowledge(alert_id: int, actor_name: str = Header(default=None, alias="X-Demo-Actor")):
    return json_result(alerts.acknowledge_alert(alert_id, clinic.normalize_actor(actor_name)))


@app.post("/api/alerts/{alert_id}/resolve")
def resolve(alert_id: int, payload: dict, actor_name: str = Header(default=None, alias="X-Demo-Actor")):
    return json_result(
        alerts.resolve_alert(
            alert_id,
            clinic.normalize_actor(actor_name),
            (payload or {}).get("note", ""),
        )
    )


@app.post("/api/alerts/{alert_id}/caregiver-response")
def caregiver_response(
    alert_id: int,
    payload: dict,
    actor_name: str = Header(default=None, alias="X-Demo-Actor"),
):
    return json_result(
        alerts.caregiver_respond(
            alert_id,
            clinic.normalize_actor(actor_name),
            (payload or {}).get("response", ""),
        )
    )


@app.get("/api/patients/{patient_id}/notes")
def patient_notes(patient_id: str):
    if db.get_patient(patient_id) is None:
        raise clinic.NotFound(f"patient {patient_id} not found")
    return json_result(clinic.list_notes(patient_id))


@app.post("/api/patients/{patient_id}/notes")
def add_patient_note(
    patient_id: str,
    payload: dict,
    actor_name: str = Header(default=None, alias="X-Demo-Actor"),
):
    return json_result(
        clinic.add_note(
            patient_id,
            clinic.normalize_actor(actor_name),
            (payload or {}).get("kind", "clinical"),
            (payload or {}).get("text", ""),
        )
    )


@app.get("/api/patients/{patient_id}/audit")
def patient_audit(patient_id: str):
    if db.get_patient(patient_id) is None:
        raise clinic.NotFound(f"patient {patient_id} not found")
    return json_result(clinic.get_patient_audit(patient_id))


@app.post("/api/patients/{patient_id}/follow-up")
def patient_follow_up(
    patient_id: str,
    payload: dict,
    actor_name: str = Header(default=None, alias="X-Demo-Actor"),
):
    return json_result(
        clinic.set_follow_up(
            patient_id,
            (payload or {}).get("next_review_at", ""),
            clinic.normalize_actor(actor_name),
            (payload or {}).get("note"),
        )
    )


@app.get("/api/care/tasks")
def care_tasks(patient_id: str | None = None):
    if patient_id is None:
        return json_result({"patient": None, "tasks": []})
    detail = clinic.get_patient_detail(patient_id)
    tasks = [
        {**row, "instruction": alerts.care_instruction(row)}
        for row in detail["open_alerts"]
    ]
    return json_result({"patient": detail["patient"], "tasks": tasks})


@app.get("/api/devices/unassigned")
def unassigned_devices():
    return json_result({"devices": clinic.unassigned_devices()})


@app.post("/api/devices/{device_id}/recalibrate")
def recalibrate(device_id: str):
    if not ingestor.connected:
        raise HTTPException(status_code=503, detail="MQTT broker not connected")
    ingestor.publish_cmd(device_id, "recalibrate")
    ingestor.reset_calibration(device_id)
    ingestor.engine.reset(device_id)
    db.reset_baseline(device_id)
    return {"ok": True, "device_id": device_id}


@app.get("/api/export.csv")
def export_csv():
    rows = db.get_export_vitals()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "time",
            "device_id",
            "heart_rate_bpm",
            "spo2_percent",
            "hrv_ms",
            "temperature_c",
            "finger",
            "state",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                row["ts"],
                row["device_id"],
                row["hr"],
                row["spo2"],
                row["hrv"],
                row["temp"],
                row["finger"],
                row["state"],
            ]
        )
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=health-history.csv"
        },
    )
