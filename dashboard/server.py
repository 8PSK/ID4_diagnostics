import asyncio
import json

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from id4.elm327 import ELM327Transport
from id4.storage import TelemetryStorage
from id4.telemetry import BatteryTelemetry


CONFIG = json.loads(
    Path("config.json").read_text()
)

transport = None
storage = None
telemetry = None
poll_task = None


@asynccontextmanager
async def lifespan(app):
    global transport, storage, telemetry, poll_task

    adapter_config = CONFIG["adapter"]
    database_config = CONFIG["database"]

    transport = ELM327Transport(
        port=adapter_config["port"],
        baudrate=adapter_config["baudrate"],
        timeout=adapter_config["timeout"]
    )

    storage = TelemetryStorage(
        database_config["sqlite"]
    )

    telemetry = BatteryTelemetry(
        transport,
        database_config["signals"],
        storage
    )

    poll_task = asyncio.create_task(
        telemetry.run()
    )

    try:
        yield
    finally:
        telemetry.stop()

        if poll_task:
            await poll_task

        if transport:
            transport.close()

        if storage:
            storage.close()


app = FastAPI(
    title="VW ID.4 Live Telemetry",
    version="1.0.0",
    lifespan=lifespan
)


@app.get("/")
async def home():
    return FileResponse(
        "dashboard/static/index.html"
    )


@app.get("/health")
async def health():
    return {
        "status": "running",
        "vehicle": CONFIG["vehicle"],
        "signals_enabled": len(telemetry.signals)
    }


@app.get("/api/telemetry")
async def get_telemetry():
    return telemetry.latest


@app.get("/api/history/{signal}")
async def get_history(signal: str, limit: int = 100):
    if not 1 <= limit <= 1000:
        return {"error": "Limit must be 1-1000"}

    return storage.history(signal, limit)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):

    await websocket.accept()

    try:
        while True:
            await websocket.send_json(
                telemetry.latest
            )

            await asyncio.sleep(0.5)

    except WebSocketDisconnect:
        pass
