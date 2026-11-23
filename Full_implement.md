I'll lay out the complete project as individual files, ready to copy into a Linux directory. This version consolidates the earlier examples and fixes several important issues:

- Correct 29-bit CAN protocol selection (`ATSP8`).
- USB serial ELM327 support.
- Read-only UDS requests.
- Response validation and diagnostic error handling.
- MEB CSV importer.
- Battery signal database with unverified signals disabled.
- Shared telemetry polling.
- SQLite historical logging.
- FastAPI WebSocket server.
- Live battery dashboard.
- Adapter diagnostic utility.

Important: The generic ELM327 interface is hardware-dependent. The project includes adapter verification and fails closed when communication or decoding is uncertain. It does not assume that accepting an AT command proves successful vehicle communication.

## Project structure

Create this directory structure:

text

```text
id4-telemetry/
├── requirements.txt
├── config.json
├── main.py
├── id4/
│   ├── __init__.py
│   ├── elm327.py
│   ├── uds.py
│   ├── decoder.py
│   ├── importer.py
│   ├── storage.py
│   └── telemetry.py
├── tools/
│   ├── probe_elm327.py
│   └── import_meb.py
├── dashboard/
│   ├── __init__.py
│   ├── server.py
│   └── static/
│       └── index.html
└── data/
    ├── signals.json
    └── raw/
```

## File 1 — `requirements.txt`

text

```text

pyserial>=3.5
fastapi>=0.115
uvicorn[standard]>=0.30
pydantic>=2.8
```

## File 2 — `config.json`

This contains your vehicle and adapter settings.

json

```json

{
  "vehicle": {
    "make": "Volkswagen",
    "model": "ID.4",
    "year": 2022,
    "platform": "MEB"
  },
  "adapter": {
    "type": "elm327",
    "port": "/dev/ttyUSB0",
    "baudrate": 38400,
    "protocol": "8",
    "timeout": 5,
    "extended_can": true
  },
  "polling": {
    "default_interval": 5,
    "minimum_interval": 2
  },
  "database": {
    "signals": "data/signals.json",
    "sqlite": "data/telemetry.db"
  },
  "dashboard": {
    "host": "127.0.0.1",
    "port": 8000
  }
}
```

## File 3 — `id4/__init__.py`

python

```python

"""VW ID.4 read-only telemetry package."""
```

## File 4 — `id4/elm327.py`

This is the USB serial adapter implementation. It handles adapter initialization, extended CAN headers, response filtering, and single-frame ISO-TP responses.

It deliberately rejects unsupported multi-frame responses instead of silently decoding incomplete data.

python

```python

import re
import time
import serial


class ELM327Error(Exception):
    pass


class ELM327Transport:

    def __init__(
        self,
        port="/dev/ttyUSB0",
        baudrate=38400,
        timeout=5
    ):
        self.timeout = timeout

        self.ser = serial.Serial(
            port=port,
            baudrate=baudrate,
            timeout=0.2,
            write_timeout=2
        )

        time.sleep(0.5)
        self.ser.reset_input_buffer()

        self.initialize()

    def command(self, command, timeout=None):
        self.ser.reset_input_buffer()

        self.ser.write(
            (command + "\r").encode("ascii")
        )

        result = bytearray()
        deadline = (
            time.monotonic()
            + (timeout or self.timeout)
        )

        while time.monotonic() < deadline:
            chunk = self.ser.read(256)

            if chunk:
                result.extend(chunk)

                if b">" in result:
                    break

        response = result.decode(
            "ascii",
            errors="replace"
        )

        response = response.replace(">", "").strip()

        upper = response.upper()

        if "?" in upper:
            raise ELM327Error(
                f"Unsupported command {command}: {response}"
            )

        if "UNABLE TO CONNECT" in upper:
            raise ELM327Error(response)

        if "STOPPED" in upper:
            raise ELM327Error(response)

        return response

    def initialize(self):
        self.command("ATZ", timeout=8)

        settings = [
            "ATE0",
            "ATL0",
            "ATS1",
            "ATH1",
            "ATSP8",
            "ATCAF1",
            "ATCFC1"
        ]

        for setting in settings:
            response = self.command(setting)

            if "OK" not in response.upper():
                raise ELM327Error(
                    f"Failed initialization: {setting}: "
                    f"{response}"
                )

        protocol = self.command("ATDPN").strip()

        if protocol.upper() not in ("8", "8?"):
            raise ELM327Error(
                f"Expected protocol 8, got {protocol}"
            )

    def configure_ecu(self, tx_id, rx_id):
        if not 0 <= tx_id <= 0x1FFFFFFF:
            raise ValueError("Invalid TX CAN ID")

        if not 0 <= rx_id <= 0x1FFFFFFF:
            raise ValueError("Invalid RX CAN ID")

        self.command(f"ATSH{tx_id:08X}")
        self.command(f"ATCRA{rx_id:08X}")

    @staticmethod
    def parse_single_frame(response, expected_rx_id, expected_did):
        """
        Parse an ELM327 response with CAN headers enabled
        and automatic CAN formatting enabled.

        Supports ISO-TP single-frame responses only.
        Multi-frame responses are rejected.
        """

        for line in response.splitlines():
            line = line.strip().upper()

            if not line:
                continue

            if any(
                x in line
                for x in (
                    "SEARCHING",
                    "NO DATA",
                    "BUS INIT",
                    "OK"
                )
            ):
                continue

            match = re.fullmatch(
                r"([0-9A-F]{8})\s+"
                r"((?:[0-9A-F]{2}\s*)+)",
                line
            )

            if not match:
                continue

            can_id = int(match.group(1), 16)

            if can_id != expected_rx_id:
                continue

            data = bytes.fromhex(match.group(2))

            if not data:
                continue

            pci_type = data[0] >> 4

            if pci_type == 1:
                raise ELM327Error(
                    "Multi-frame ISO-TP response detected. "
                    "This ELM response parser has not yet "
                    "validated multi-frame reassembly."
                )

            if pci_type != 0:
                continue

            length = data[0] & 0x0F

            if length > 7 or len(data) < length + 1:
                raise ELM327Error(
                    "Invalid ISO-TP single-frame length"
                )

            payload = data[1:1 + length]

            if len(payload) < 3:
                raise ELM327Error("UDS response too short")

            if payload[0] == 0x7F:
                service = payload[1]
                code = payload[2]

                raise ELM327Error(
                    f"UDS negative response: "
                    f"service=0x{service:02X}, "
                    f"NRC=0x{code:02X}"
                )

            if payload[0] != 0x62:
                raise ELM327Error(
                    f"Unexpected UDS service: "
                    f"0x{payload[0]:02X}"
                )

            did = int.from_bytes(
                payload[1:3],
                "big"
            )

            if did != expected_did:
                raise ELM327Error("Unexpected DID")

            return payload

        raise ELM327Error(
            f"No valid response for DID "
            f"0x{expected_did:04X}: {response}"
        )

    def read_did(self, tx_id, rx_id, did):
        if not 0 <= did <= 0xFFFF:
            raise ValueError("Invalid DID")

        self.configure_ecu(tx_id, rx_id)

        # UDS service 0x22 only.
        # ELM automatic formatting supplies ISO-TP framing.
        response = self.command(
            f"22{did:04X}"
        )

        return self.parse_single_frame(
            response,
            rx_id,
            did
        )

    def close(self):
        if self.ser and self.ser.is_open:
            self.ser.close()
```

Compatibility limitation: This first transport implementation is intentionally single-frame only. It is suitable for adapter qualification and short responses, not a complete implementation for all battery measurements. Cell arrays and other long DIDs require a separately validated multi-frame ISO-TP path. Don't enable those signals yet.

## File 5 — `id4/uds.py`

python

```python

class UDSClient:

    def __init__(self, transport):
        self.transport = transport

    def read_data_by_identifier(
        self,
        tx_id,
        rx_id,
        did
    ):
        response = self.transport.read_did(
            tx_id,
            rx_id,
            did
        )

        if len(response) < 3:
            raise ValueError("Invalid UDS response")

        if response[0] != 0x62:
            raise ValueError("Not a positive 0x22 response")

        response_did = int.from_bytes(
            response[1:3],
            "big"
        )

        if response_did != did:
            raise ValueError("DID mismatch")

        return response[3:]
```

## File 6 — `id4/decoder.py`

python

```python

def decode_signal(signal, payload):

    if not signal.get("verified", False):
        raise ValueError(
            f"Signal not verified: {signal['name']}"
        )

    length = signal.get("byte_length")
    scale = signal.get("scale")
    offset = signal.get("offset")

    if not isinstance(length, int) or length < 1:
        raise ValueError("Invalid byte length")

    if scale is None or offset is None:
        raise ValueError("Missing conversion formula")

    if len(payload) != length:
        raise ValueError(
            f"Expected {length} bytes, "
            f"received {len(payload)}"
        )

    datatype = signal.get("datatype", "uint")

    if datatype == "uint":
        raw = int.from_bytes(payload, "big")

    elif datatype == "int":
        raw = int.from_bytes(
            payload,
            "big",
            signed=True
        )

    else:
        raise ValueError(
            f"Unsupported datatype: {datatype}"
        )

    value = raw * scale + offset

    return {
        "name": signal["name"],
        "value": round(value, 3),
        "unit": signal["unit"],
        "raw": raw
    }
```

## File 7 — `id4/storage.py`

This stores telemetry locally in SQLite, including raw values and timestamps.

python

```python

import sqlite3
import json
import time
from pathlib import Path


class TelemetryStorage:

    def __init__(self, database):
        Path(database).parent.mkdir(
            parents=True,
            exist_ok=True
        )

        self.connection = sqlite3.connect(
            database,
            check_same_thread=False
        )

        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS telemetry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                signal TEXT NOT NULL,
                value REAL,
                unit TEXT,
                raw INTEGER,
                status TEXT NOT NULL,
                error TEXT
            )
        """)

        self.connection.commit()

    def save(self, name, result):
        self.connection.execute(
            """
            INSERT INTO telemetry
            (timestamp, signal, value, unit,
             raw, status, error)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.get("timestamp", time.time()),
                name,
                result.get("value"),
                result.get("unit"),
                result.get("raw"),
                result.get("status", "valid"),
                result.get("error")
            )
        )

        self.connection.commit()

    def history(self, signal, limit=100):
        cursor = self.connection.execute(
            """
            SELECT timestamp, value, unit, status
            FROM telemetry
            WHERE signal = ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (signal, limit)
        )

        return [
            {
                "timestamp": row[0],
                "value": row[1],
                "unit": row[2],
                "status": row[3]
            }
            for row in cursor.fetchall()
        ]

    def close(self):
        self.connection.close()
```

## File 8 — `id4/telemetry.py`

This implements a single polling loop shared by all dashboard clients.

python

```python

import asyncio
import json
import time

from pathlib import Path

from id4.uds import UDSClient
from id4.decoder import decode_signal


class BatteryTelemetry:

    def __init__(
        self,
        transport,
        database,
        storage
    ):
        config = json.loads(
            Path(database).read_text()
        )

        self.transport = transport
        self.uds = UDSClient(transport)
        self.storage = storage

        self.ecus = config["ecus"]

        self.signals = [
            signal
            for signal in config["signals"]
            if signal.get("enabled")
            and signal.get("verified")
        ]

        self.latest = {}
        self.running = False

    async def poll_signal(self, signal):
        ecu = self.ecus[signal["ecu"]]

        tx_id = int(ecu["tx_id"], 16)
        rx_id = int(ecu["rx_id"], 16)
        did = int(signal["did"], 16)

        payload = await asyncio.to_thread(
            self.uds.read_data_by_identifier,
            tx_id,
            rx_id,
            did
        )

        decoded = decode_signal(
            signal,
            payload
        )

        decoded["timestamp"] = time.time()
        decoded["status"] = "valid"

        self.latest[signal["name"]] = decoded

        await asyncio.to_thread(
            self.storage.save,
            signal["name"],
            decoded
        )

    async def run(self):
        self.running = True

        next_poll = {
            s["name"]: 0
            for s in self.signals
        }

        while self.running:
            now = time.monotonic()

            for signal in self.signals:
                name = signal["name"]

                if now < next_poll[name]:
                    continue

                try:
                    await self.poll_signal(signal)

                except Exception as exc:
                    result = {
                        "name": name,
                        "status": "error",
                        "error": str(exc),
                        "timestamp": time.time()
                    }

                    self.latest[name] = result

                    await asyncio.to_thread(
                        self.storage.save,
                        name,
                        result
                    )

                interval = max(
                    2,
                    float(signal.get("interval", 5))
                )

                next_poll[name] = (
                    time.monotonic() + interval
                )

            await asyncio.sleep(0.1)

    def stop(self):
        self.running = False
```

## File 9 — `tools/probe_elm327.py`

python

```python

import argparse
import json
import time
import serial


def command(ser, value, timeout=5):
    ser.reset_input_buffer()
    ser.write((value + "\r").encode())

    result = bytearray()
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        result.extend(ser.read(256))

        if b">" in result:
            break

    return result.decode(
        errors="replace"
    ).replace(">", "").strip()


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--port",
        default="/dev/ttyUSB0"
    )

    parser.add_argument(
        "--baud",
        type=int,
        default=38400
    )

    args = parser.parse_args()

    report = {}

    with serial.Serial(
        args.port,
        args.baud,
        timeout=0.2
    ) as ser:

        time.sleep(0.5)

        commands = [
            "ATZ",
            "ATI",
            "ATE0",
            "ATL0",
            "ATS1",
            "ATH1",
            "ATSP8",
            "ATDPN",
            "ATCAF1",
            "ATCFC1"
        ]

        for cmd in commands:
            try:
                response = command(
                    ser,
                    cmd,
                    timeout=8 if cmd == "ATZ" else 5
                )

                report[cmd] = response

                print(
                    f"{cmd:10} -> {response}"
                )

            except Exception as exc:
                report[cmd] = str(exc)
                print(cmd, "FAILED:", exc)

    with open(
        "data/adapter_report.json",
        "w"
    ) as file:
        json.dump(report, file, indent=2)


if __name__ == "__main__":
    main()
```

## File 10 — `tools/import_meb.py`

This importer preserves the source CSV records and extracts recognizable CAN request/response information. It doesn't assume that a DID's scaling formula is universal.

python

```python

import csv
import json
import re
import argparse

from pathlib import Path


def find_column(row, candidates):
    for key in row:
        normalized = key.lower().strip()

        for candidate in candidates:
            if candidate in normalized:
                return key

    return None


def extract_can_package(value):
    if not value:
        return None

    match = re.search(
        r"0x([0-9a-fA-F]{8})\s+"
        r"((?:[0-9a-fA-F]{2}\s*)+)",
        value
    )

    if not match:
        return None

    return {
        "can_id": int(match.group(1), 16),
        "bytes": [
            int(x, 16)
            for x in match.group(2).split()
        ]
    }


def import_database(source, destination):
    records = []

    with open(
        source,
        encoding="utf-8-sig",
        newline=""
    ) as file:

        sample = file.read(4096)
        file.seek(0)

        delimiter = ";" if sample.count(";") > sample.count(",") else ","

        reader = csv.DictReader(
            file,
            delimiter=delimiter
        )

        for row in reader:
            name_col = find_column(
                row,
                ["popular name", "name"]
            )

            request_col = find_column(
                row,
                ["request package", "request"]
            )

            response_col = find_column(
                row,
                ["response package", "response"]
            )

            calculation_col = find_column(
                row,
                ["calculation", "formula"]
            )

            unit_col = find_column(
                row,
                ["unit"]
            )

            request = extract_can_package(
                row.get(request_col, "")
                if request_col else ""
            )

            response = extract_can_package(
                row.get(response_col, "")
                if response_col else ""
            )

            payload = (
                request["bytes"]
                if request else []
            )

            did = None

            if len(payload) >= 4 and payload[1] == 0x22:
                did = (
                    (payload[2] << 8)
                    | payload[3]
                )

            records.append({
                "name": (
                    row.get(name_col, "")
                    if name_col else ""
                ),
                "unit": (
                    row.get(unit_col, "")
                    if unit_col else ""
                ),
                "did": (
                    f"0x{did:04X}"
                    if did is not None else None
                ),
                "request": request,
                "response": response,
                "formula": (
                    row.get(calculation_col, "")
                    if calculation_col else ""
                ),
                "source_record": row,
                "verified": False,
                "enabled": False
            })

    Path(destination).parent.mkdir(
        parents=True,
        exist_ok=True
    )

    Path(destination).write_text(
        json.dumps(records, indent=2),
        encoding="utf-8"
    )

    print("Imported records:", len(records))
    print("Output:", destination)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument("source")
    parser.add_argument(
        "--output",
        default="data/meb_catalog.json"
    )

    args = parser.parse_args()

    import_database(
        args.source,
        args.output
    )
```

## File 11 — `data/signals.json`

This is the initial 2022 ID.4 battery profile.

The ECU addressing below is a candidate from the MEB community parameter definitions. Verify it against the original source and your vehicle before use.

All signals are disabled because their response lengths and conversion formulas must be validated first.

json

```json

{
  "vehicle": {
    "make": "Volkswagen",
    "model": "ID.4",
    "year": 2022,
    "platform": "MEB"
  },
  "ecus": {
    "bms": {
      "name": "Battery Management System",
      "tx_id": "0x17FC007B",
      "rx_id": "0x17FE007B"
    }
  },
  "signals": [
    {
      "name": "battery_soc",
      "description": "BMS state of charge",
      "ecu": "bms",
      "did": "0x028C",
      "unit": "%",
      "datatype": "uint",
      "byte_length": null,
      "scale": null,
      "offset": null,
      "interval": 5,
      "enabled": false,
      "verified": false
    },
    {
      "name": "battery_voltage",
      "description": "High voltage battery voltage",
      "ecu": "bms",
      "did": "0x1E3B",
      "unit": "V",
      "datatype": "uint",
      "byte_length": null,
      "scale": null,
      "offset": null,
      "interval": 5,
      "enabled": false,
      "verified": false
    },
    {
      "name": "battery_temperature",
      "description": "High voltage battery temperature",
      "ecu": "bms",
      "did": "0x2A0B",
      "unit": "°C",
      "datatype": "uint",
      "byte_length": null,
      "scale": null,
      "offset": null,
      "interval": 10,
      "enabled": false,
      "verified": false
    },
    {
      "name": "battery_temperature_1",
      "description": "Battery temperature sensor 1",
      "ecu": "bms",
      "did": "0x1EAE",
      "unit": "°C",
      "datatype": "uint",
      "byte_length": null,
      "scale": null,
      "offset": null,
      "interval": 10,
      "enabled": false,
      "verified": false
    },
    {
      "name": "charge_current_limit",
      "description": "Maximum charging current",
      "ecu": "bms",
      "did": "0x1E1B",
      "unit": "A",
      "datatype": "uint",
      "byte_length": null,
      "scale": null,
      "offset": null,
      "interval": 10,
      "enabled": false,
      "verified": false
    },
    {
      "name": "discharge_current_limit",
      "description": "Maximum discharge current",
      "ecu": "bms",
      "did": "0x1E1C",
      "unit": "A",
      "datatype": "uint",
      "byte_length": null,
      "scale": null,
      "offset": null,
      "interval": 10,
      "enabled": false,
      "verified": false
    }
  ]
}
```

## File 12 — `dashboard/__init__.py`

python

```python

"""Dashboard package."""
```

## File 13 — `dashboard/server.py`

This runs one shared telemetry task, serves the dashboard, and broadcasts the latest values to WebSocket clients.

python

```python

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

    yield

    telemetry.stop()

    if poll_task:
        await poll_task

    if transport:
        transport.close()

    if storage:
        storage.close()


app = FastAPI(
    title="VW ID.4 Telemetry",
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
        last_snapshot = None

        while True:
            snapshot = telemetry.latest

            if snapshot != last_snapshot:
                await websocket.send_json(snapshot)
                last_snapshot = dict(snapshot)

            await asyncio.sleep(0.5)

    except WebSocketDisconnect:
        pass
```

## File 14 — `dashboard/static/index.html`

This is the live dashboard interface. It shows unavailable values as `--` rather than inventing measurements.

HTMLWrap linesCopy codePreview

```html

<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ID.4 Battery Monitor</title>

<style>
:root {
  color-scheme: dark;
  font-family: system-ui, sans-serif;
  background: #101720;
  color: #f4f7fb;
}

body {
  margin: 0;
  padding: 24px;
  max-width: 1200px;
  margin-inline: auto;
}

h1 { font-size: 27px; }

.subtitle {
  color: #9caaba;
  margin-bottom: 25px;
}

.status {
  display: inline-block;
  background: #253545;
  border-radius: 20px;
  padding: 8px 14px;
  margin-bottom: 20px;
  font-size: 13px;
}

.grid {
  display: grid;
  grid-template-columns: repeat(
    auto-fit, minmax(190px, 1fr)
  );
  gap: 15px;
}

.card {
  background: #202c3a;
  padding: 20px;
  border-radius: 14px;
  min-height: 100px;
}

.name {
  color: #a8b6c6;
  font-size: 14px;
}

.value {
  font-size: 30px;
  font-weight: 650;
  margin-top: 15px;
}

.unit {
  color: #a8b6c6;
  font-size: 14px;
}

.error {
  color: #ff9999;
  font-size: 12px;
  margin-top: 8px;
}

.section {
  margin: 28px 0 14px;
}

.footer {
  color: #8190a1;
  font-size: 12px;
  margin-top: 30px;
}
</style>
</head>

<body>

<h1>Volkswagen ID.4</h1>

<div class="subtitle">
2022 MEB Battery Monitoring
</div>

<div class="status" id="status">
Connecting to telemetry service...
</div>

<h2 class="section">Battery information</h2>

<div class="grid" id="battery"></div>

<h2 class="section">Other telemetry</h2>

<div class="grid" id="other"></div>

<div class="footer">
Local read-only diagnostic monitoring.
No ECU coding or vehicle control.
</div>

<script>
const labels = {
  battery_soc: "Battery SOC",
  battery_voltage: "HV battery voltage",
  battery_temperature: "Battery temperature",
  battery_temperature_1: "Battery sensor 1",
  charge_current_limit: "Charge current limit",
  discharge_current_limit: "Discharge current limit"
};

const batteryNames = Object.keys(labels);

const status = document.getElementById("status");
const battery = document.getElementById("battery");
const other = document.getElementById("other");

function makeCard(name, item) {
  const card = document.createElement("div");
  card.className = "card";

  const title = document.createElement("div");
  title.className = "name";
  title.textContent = labels[name] || name;

  const value = document.createElement("div");
  value.className = "value";

  if (item.status === "valid") {
    value.textContent = item.value;

    const unit = document.createElement("span");
    unit.className = "unit";
    unit.textContent = " " + (item.unit || "");

    value.append(unit);
  } else {
    value.textContent = "--";

    const error = document.createElement("div");
    error.className = "error";
    error.textContent =
      item.error || "Waiting for verified signal";
    card.append(error);
  }

  card.append(title, value);
  return card;
}

function update(data) {
  battery.replaceChildren();
  other.replaceChildren();

  for (const name of batteryNames) {
    const item = data[name] || {
      status: "waiting"
    };

    battery.append(makeCard(name, item));
  }

  for (const [name, item] of Object.entries(data)) {
    if (!batteryNames.includes(name)) {
      other.append(makeCard(name, item));
    }
  }
}

function connect() {
  const scheme =
    location.protocol === "https:" ? "wss" : "ws";

  const ws = new WebSocket(
    `${scheme}://${location.host}/ws`
  );

  ws.onopen = () => {
    status.textContent = "Connected to local telemetry";
  };

  ws.onmessage = event => {
    update(JSON.parse(event.data));
  };

  ws.onclose = () => {
    status.textContent = "Disconnected - reconnecting";
    setTimeout(connect, 3000);
  };

  ws.onerror = () => {
    status.textContent = "Telemetry connection error";
  };
}

connect();
</script>

</body>
</html>
```

## File 15 — `main.py`

python

```python

import json
import uvicorn

from pathlib import Path


def main():
    config = json.loads(
        Path("config.json").read_text()
    )

    uvicorn.run(
        "dashboard.server:app",
        host=config["dashboard"]["host"],
        port=config["dashboard"]["port"],
        reload=False
    )


if __name__ == "__main__":
    main()
```

# Installation and launch

Once you've created the files, run these commands from the project directory.

### 1. Install dependencies

bash

```bash
sudo apt install python3-venv python3-pip

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Verify the adapter

Connect the ELM327 to USB:

bash

```bash
python tools/probe_elm327.py \
    --port /dev/ttyUSB0 \
    --baud 38400
```

If necessary, change the serial port in `config.json`.

### 3. Download the MEB database

bash

```bash
curl -L \
"https://raw.githubusercontent.com/spot2000/Volkswagen-MEB-EV-CAN-parameters/main/VW%20MEB%20UDS%20PIDs%20list.csv" \
-o data/meb.csv
```

Import:

bash

```bash
python tools/import_meb.py data/meb.csv
```

This creates:

text

```text
data/meb_catalog.json
```

It is a source catalog, not an automatically validated executable signal configuration.

### 4. Start the dashboard

bash

```bash
python main.py
```

Open:

[Open ID.4 Battery Dashboard](<http://127.0.0.1:8000?utm_source=chatgpt.com>)

### 5. Check the API

bash

```bash
curl http://127.0.0.1:8000/health
```

WebSocket:

text

```text
ws://127.0.0.1:8000/ws
```

## What is implemented versus what remains

Implemented in this project

Linux USB serial connection

ELM327 identification and configuration

Extended CAN protocol selection

Read-only UDS 0x22 request interface

Single-frame ISO-TP response parsing

MEB CSV source importer

Validated-signal-only decoder

Shared polling service

SQLite telemetry history

FastAPI and WebSocket dashboard

Still requires hardware-specific development

Multi-frame ISO-TP response reassembly

Validation of actual 2022 ID.4 BMS addressing

Verification of individual DID lengths and formulas

Battery cell voltage and temperature decoding

Charging and powertrain ECU profiles

One particularly important limitation: This is a complete starter project, not yet a complete working ID.4 diagnostic implementation. The battery signals are deliberately disabled, and the current ELM327 parser rejects multi-frame responses. Don't enable them by simply copying scaling values from earlier examples.

## My recommended next step

Run the adapter probe and send me `data/adapter_report.json`, along with the output of:

bash

```bash
lsusb
python3 -m serial.tools.list_ports -v
```

The next development step should be a proper ISO-TP multi-frame implementation for your specific ELM327, followed by validating the BMS SOC DID. That will unlock the longer battery measurements and make the dashboard genuinely useful.