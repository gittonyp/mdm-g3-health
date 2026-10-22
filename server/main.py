import csv
import io
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse

from . import config, db
from .mqtt_ingest import MqttIngestor

ingestor = MqttIngestor()


@asynccontextmanager
async def lifespan(app):
    db.init_db()
    ingestor.start()
    yield
    ingestor.stop()


app = FastAPI(title="MDM G3 Health API", lifespan=lifespan)


@app.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(config.ROOT_DIR / "health_dashboard.html")


@app.get("/history", include_in_schema=False)
def history():
    return FileResponse(config.ROOT_DIR / "server" / "static" / "history.html")


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


@app.post("/api/devices/{device_id}/recalibrate")
def recalibrate(device_id: str):
    if not ingestor.connected:
        raise HTTPException(status_code=503, detail="MQTT broker not connected")
    ingestor.publish_cmd(device_id, "recalibrate")
    ingestor.reset_calibration(device_id)
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
