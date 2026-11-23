# Refining the VW ID.4 telemetry system for Linux + USB ELM327

For your setup, I'd use Python on Linux with a USB serial ELM327 adapter, keeping the vehicle communication completely read-only.

There is one important change I'd make to the earlier implementation: don't immediately start querying the battery ECU. First establish whether the generic ELM327 can actually communicate using the ID.4's extended CAN addressing.

A generic ELM327 may work, but its firmware version and implementation matter more than the label printed on the adapter.

The development plan is:

1. Identify the USB adapter and serial interface.
2. Test its ELM327 command support without sending diagnostic requests to the car.
3. Verify 29-bit CAN and 500 kbit/s support.
4. Implement a robust ISO-TP/UDS read-only communication layer.
5. Import and validate MEB battery signal definitions.
6. Build a battery telemetry service with WebSocket updates.
7. Add logging, error handling, and dashboard monitoring.

## 1. Linux USB setup

First install the system dependencies:

bash

```bash
sudo apt update

sudo apt install -y \
    python3 \
    python3-venv \
    python3-pip \
    python3-serial \
    git \
    usbutils
```

Plug in your ELM327 and run:

bash

```bash
lsusb
```

Then:

bash

```bash
dmesg | tail -30
```

Look for a serial device such as:

- `/dev/ttyUSB0`
- `/dev/ttyACM0`

Check available serial interfaces:

bash

```bash
python3 -m serial.tools.list_ports -v
```

Add your Linux user to the serial device group:

bash

```bash
sudo usermod -aG dialout "$USER"
```

Log out and back in for the group change to take effect.

### Create the project

bash

```bash
mkdir -p ~/id4-telemetry/{id4,tools,data/raw,dashboard/static}
cd ~/id4-telemetry

touch id4/__init__.py
touch tools/__init__.py
touch dashboard/__init__.py

python3 -m venv .venv
source .venv/bin/activate

pip install pyserial fastapi uvicorn[standard] pydantic
```

## 2. Adapter verification

This is the first script I'd run.

It identifies the ELM327 firmware, checks supported commands, and selects the extended CAN protocol without sending any ECU diagnostic requests.

For the ID.4 configuration, the important protocol is:

| Setting | Value |
| --- | --- |
| CAN speed | 500 kbit/s |
| CAN addressing | 29-bit extended |
| ELM protocol | `8` |
| Python interface | USB serial |
| Diagnostic mode | Read-only |

Important: ELM protocol 8 is ISO 15765-4 CAN with 29-bit identifiers at 500 kbit/s. Protocol 7 is 11-bit CAN, so the earlier example's `ATSP7` setting should not be used for the extended-address configuration.

### Create `tools/probe_elm327.py`

python

```python

import argparse
import time
import serial


class ELMProbe:
    def __init__(self, port, baud):
        self.ser = serial.Serial(
            port=port,
            baudrate=baud,
            timeout=0.2,
            write_timeout=2
        )

        time.sleep(0.5)
        self.ser.reset_input_buffer()

    def command(self, cmd, timeout=4):
        self.ser.reset_input_buffer()

        self.ser.write((cmd + "\r").encode("ascii"))

        result = bytearray()
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            chunk = self.ser.read(256)

            if chunk:
                result.extend(chunk)

                if b">" in result:
                    break

        return result.decode(
            "ascii",
            errors="replace"
        ).replace(">", "").strip()

    def run(self):
        commands = [
            ("ATZ", "Reset"),
            ("ATI", "Adapter identification"),
            ("ATE0", "Echo off"),
            ("ATL0", "Linefeeds off"),
            ("ATS1", "Spaces on"),
            ("ATH1", "Headers on"),
            ("ATSP8", "Select extended 29-bit CAN"),
            ("ATDP", "Protocol description"),
            ("ATDPN", "Protocol number"),
            ("ATCAF1", "Automatic CAN formatting"),
            ("ATCFC1", "Automatic ISO-TP flow control")
        ]

        report = {}

        for command, description in commands:
            try:
                result = self.command(command)

                report[command] = {
                    "description": description,
                    "response": result
                }

                print(
                    f"{command:10} "
                    f"{description:35} "
                    f"{result}"
                )

            except Exception as exc:
                report[command] = {
                    "error": str(exc)
                }

                print(command, "FAILED:", exc)

        self.ser.close()

        return report


if __name__ == "__main__":
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

    probe = ELMProbe(
        args.port,
        args.baud
    )

    probe.run()
```

Run:

bash

```bash
python tools/probe_elm327.py \
    --port /dev/ttyUSB0 \
    --baud 38400
```

If you get no response, try another baud rate:

bash

```bash
python tools/probe_elm327.py --baud 9600
```

Or:

bash

```bash
python tools/probe_elm327.py --baud 115200
```

The probe changes adapter configuration but does not issue a UDS request, write to an ECU, or modify vehicle coding. Some commands may be unsupported by clones.

### How to interpret the result

| Result | Meaning |
| --- | --- |
| `ATI` returns ELM327 identification | Serial communication works |
| `ATSP8` returns OK | Adapter accepts protocol selection |
| `ATDPN` returns `8` | Extended CAN protocol selected |
| `ATCAF1` returns OK | Automatic CAN formatting accepted |
| `ATCFC1` returns OK | Automatic flow control accepted |

An `OK` response only confirms that firmware accepted a command. It does not prove that the adapter can successfully transmit and receive 29-bit CAN frames.

I would classify adapters as follows:

- Candidate: All configuration commands work.
- Unverified: Protocol 8 is accepted, but CAN communication has not been demonstrated.
- Incompatible: Extended headers, flow control, or required CAN framing are unsupported.

Don't start battery polling just because the probe returns `OK`.

## 3. Refined communication architecture

For this hardware, I would make one architectural change: keep ELM327 responsible for CAN transport and ISO-TP flow control, and let Python handle UDS and signal decoding.

Python application

`TelemetryService`

Scheduling, validation, publishing and logging

`UDSClient`

ReadDataByIdentifier (0x22), response validation

`ELM327Transport`

Serial commands, CAN headers, filtering, ISO-TP support

USB ELM327 → ID.4 BMS

29-bit CAN / 500 kbit/s

This has an advantage: if you later replace the ELM327 with a CANable or another SocketCAN adapter, the UDS and battery decoding code can remain largely unchanged.

### `id4/transport.py`

This is a safer transport abstraction. It restricts the diagnostic interface to a known ECU and explicitly allows only UDS ReadDataByIdentifier requests.

python

```python

import re
import time
import serial


class ELM327Transport:
    def __init__(
        self,
        port="/dev/ttyUSB0",
        baudrate=38400
    ):
        self.ser = serial.Serial(
            port,
            baudrate,
            timeout=0.2,
            write_timeout=2
        )

        time.sleep(0.5)
        self.ser.reset_input_buffer()

        self._command("ATE0")
        self._command("ATL0")
        self._command("ATS1")
        self._command("ATH1")
        self._command("ATSP8")
        self._command("ATCAF1")
        self._command("ATCFC1")

        protocol = self._command("ATDPN").strip()

        if protocol.upper() not in ("8", "8?"):
            raise RuntimeError(
                f"Expected ELM protocol 8, got {protocol}"
            )

    def _command(self, command, timeout=5):
        self.ser.reset_input_buffer()
        self.ser.write((command + "\r").encode())

        result = bytearray()
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            result.extend(self.ser.read(256))

            if b">" in result:
                break

        response = result.decode(
            errors="replace"
        ).replace(">", "").strip()

        if "?" in response:
            raise RuntimeError(
                f"Unsupported ELM command {command}: {response}"
            )

        if "STOPPED" in response.upper():
            raise RuntimeError(response)

        return response

    def configure_ecu(self, tx_id, rx_id):
        if not 0 <= tx_id <= 0x1FFFFFFF:
            raise ValueError("Invalid transmit CAN ID")

        if not 0 <= rx_id <= 0x1FFFFFFF:
            raise ValueError("Invalid receive CAN ID")

        self._command(f"ATSH{tx_id:08X}")
        self._command(f"ATCRA{rx_id:08X}")

    def read_did(self, tx_id, rx_id, did):
        if not 0 <= did <= 0xFFFF:
            raise ValueError("Invalid DID")

        self.configure_ecu(tx_id, rx_id)

        # Only supported diagnostic operation:
        # UDS ReadDataByIdentifier (0x22).
        request = f"22{did:04X}"

        response = self._command(
            request,
            timeout=5
        )

        return response

    def close(self):
        if self.ser.is_open:
            self.ser.close()
```

Transport qualification: This is a candidate ELM327 driver, not a validated universal implementation. `ATCAF1` behavior, extended receive filtering, response framing, and multi-frame response handling vary between clones. The returned text must be normalized and validated before being passed to the decoder. In particular, don't assume that every response is already reassembled into a UDS payload.

For the first test, use a known, confirmed ECU address and a single supported DID from the vehicle-specific database. Don't scan arbitrary CAN identifiers.

## 4. Battery signal database

I want to separate the signal definitions from the communication driver.

This makes it possible to add new MEB signals without changing Python code.

Create `data/signals.json`:

json

```json

{
  "vehicle": {
    "make": "Volkswagen",
    "model": "ID.4",
    "model_year": 2022,
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
      "offset": 0,
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
      "offset": 0,
      "interval": 5,
      "enabled": false,
      "verified": false
    },
    {
      "name": "battery_temperature",
      "description": "Battery temperature",
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
      "name": "charge_current_limit",
      "description": "Maximum charging current",
      "ecu": "bms",
      "did": "0x1E1B",
      "unit": "A",
      "datatype": "uint",
      "byte_length": null,
      "scale": null,
      "offset": 0,
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
      "offset": 0,
      "interval": 10,
      "enabled": false,
      "verified": false
    }
  ]
}
```

Notice that the signals are initially disabled.

That's intentional. I would not use the scale factors from the earlier illustrative example as verified production definitions. We need to inspect the original MEB CSV's calculation formulas, data widths, and response formats before enabling each signal.

### Improved decoder

`id4/decoder.py`

python

```python

def decode_payload(signal, payload):
    if not signal.get("verified"):
        raise ValueError(
            f"Unverified signal: {signal['name']}"
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
            f"Expected {length} bytes, got {len(payload)}"
        )

    datatype = signal.get("datatype")

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

This prevents the application from displaying plausible-looking but incorrect battery values.

## 5. Implement the battery telemetry service

I would introduce a shared polling service instead of having each dashboard connection query the car independently.

`id4/telemetry.py`

python

```python

import asyncio
import json
import time

from pathlib import Path


class BatteryTelemetry:
    def __init__(self, transport, database):
        self.transport = transport

        config = json.loads(
            Path(database).read_text()
        )

        self.ecus = config["ecus"]

        self.signals = [
            s for s in config["signals"]
            if s.get("enabled")
            and s.get("verified")
        ]

        self.latest = {}
        self.running = False

    async def read_signal(self, signal):
        ecu = self.ecus[signal["ecu"]]

        tx = int(ecu["tx_id"], 16)
        rx = int(ecu["rx_id"], 16)
        did = int(signal["did"], 16)

        response = await asyncio.to_thread(
            self.transport.read_did,
            tx,
            rx,
            did
        )

        # A production transport normalizer must convert
        # the ELM response into a validated UDS payload.
        payload = normalize_uds_response(
            response,
            did
        )

        from id4.decoder import decode_payload

        result = decode_payload(
            signal,
            payload
        )

        result["timestamp"] = time.time()
        result["status"] = "valid"

        self.latest[signal["name"]] = result

    async def run(self):
        self.running = True

        next_read = {
            s["name"]: 0
            for s in self.signals
        }

        while self.running:
            now = time.monotonic()

            for signal in self.signals:
                name = signal["name"]

                if now < next_read[name]:
                    continue

                try:
                    await self.read_signal(signal)

                except Exception as exc:
                    self.latest[name] = {
                        "status": "error",
                        "error": str(exc),
                        "timestamp": time.time()
                    }

                next_read[name] = (
                    time.monotonic()
                    + signal["interval"]
                )

            await asyncio.sleep(0.1)

    def stop(self):
        self.running = False


def normalize_uds_response(response, did):
    """
    Accepts a normalized UDS payload.

    The ELM327 text parser must be implemented and
    validated for the specific adapter before use.
    """
    if isinstance(response, bytes):
        payload = response

    else:
        raise TypeError(
            "Raw ELM text must be parsed before decoding"
        )

    if len(payload) < 3:
        raise ValueError("Response too short")

    if payload[0] != 0x62:
        raise ValueError(
            f"Unexpected UDS service: {payload[0]:02X}"
        )

    received_did = int.from_bytes(
        payload[1:3], "big"
    )

    if received_did != did:
        raise ValueError("DID mismatch")

    return payload[3:]
```

The important point here is that the telemetry service expects a normalized UDS response. The raw ELM327 text parser is a separate component and must be validated before connecting the two.

### Expected telemetry output

Once the signal definitions are validated, the API should produce JSON resembling:

json

```json
{
  "battery_soc": {
    "value": 76.4,
    "unit": "%",
    "status": "valid",
    "timestamp": 1795120000
  },
  "battery_voltage": {
    "value": 378.2,
    "unit": "V",
    "status": "valid",
    "timestamp": 1795120000
  },
  "battery_temperature": {
    "value": 24.5,
    "unit": "°C",
    "status": "valid",
    "timestamp": 1795120000
  }
}
```

Illustrative output only, not actual readings from your vehicle.

## 6. Dashboard improvements

For battery monitoring, I'd add four dashboard sections:

Battery overview

# --%

Battery SOC

# -- V

Pack voltage

Battery thermal monitoring

# -- °C

Minimum temperature

# -- °C

Maximum temperature

Charging and power

- Charging status
- Charging current
- Charging power
- Maximum charging current
- Maximum discharge current
  Battery history
- SOC over time
- Battery temperature over time
- Pack voltage over time
- Charge/discharge energy over time
  Dashboard layout proposal; actual values will appear only after verified signals are available.

For historical data, I'd use SQLite. It is lightweight, local, and suitable for a Raspberry Pi or Linux mini-PC.

I would also store raw response bytes alongside decoded measurements, so we can revisit the conversion formulas without having to reconnect to the vehicle.

## 7. Testing without the vehicle

Before connecting to the ID.4, I'd test the decoder using simulated UDS responses.

Create `tools/test_decoder.py`:

python

```python
from id4.decoder import decode_payload

signal = {
    "name": "battery_soc",
    "unit": "%",
    "verified": True,
    "datatype": "uint",
    "byte_length": 2,
    "scale": 0.4,
    "offset": 0
}

# Example only: raw value 191
payload = bytes.fromhex("00 BF")

result = decode_payload(signal, payload)

print(result)
```

Expected output:

text

```text
{'name': 'battery_soc', 'value': 76.4, 'unit': '%', 'raw': 191}
```

This tests the decoder, not the validity of that SOC conversion for your vehicle.

## 8. What I would build next

There are three significant pieces still needed before this becomes a complete working application:

| Component | Priority | Purpose |
| --- | --- | --- |
| ELM327 response normalizer | Critical | Convert actual adapter responses into UDS payloads |
| MEB CSV importer validation | Critical | Preserve ECU routing, DID, byte lengths and formulas |
| SQLite telemetry storage | High | Historical battery monitoring |
| WebSocket broadcast manager | High | Shared polling for multiple dashboard clients |
| Battery charts | High | SOC, temperature, voltage history |
| Additional ECU profiles | Medium | Charging, drivetrain and climate |

One correction to the earlier importer: the original CSV should be inspected for its actual column names and request/response formats before relying on the example parser. I would preserve the original records and generate a normalized database rather than silently discard entries that don't match an assumed format.

## 9. My recommended hardware acceptance test

1. USB detection
   Confirm Linux sees the adapter and Python can open its serial port.
   No vehicle communication required
2. ELM327 identification
   Confirm `ATI` returns a meaningful firmware identification.
3. Extended CAN configuration
   Confirm protocol 8 and automatic flow control are accepted.
4. CAN communication validation
   Verify actual 29-bit CAN transmission and reception using a suitable test setup.
5. Vehicle BMS validation
   Only then test one documented, read-only BMS DID with the vehicle parked.
6. Dashboard operation
   Validate decoded values against the vehicle display and log the measurements.

If the ELM327 fails the extended CAN tests, I'd stop there and move to a SocketCAN-compatible adapter rather than trying to work around incomplete firmware.

## 10. Your immediate next step

Run the ELM327 probe script and send me its output.

That will tell us whether we can proceed with your existing hardware or whether we should change the transport layer.

I'd also like the output of:

bash

```bash
lsusb
```

and:

bash

```bash
python3 -m serial.tools.list_ports -v
```

With those results, I can refine the driver for your actual adapter, including:

- Correct baud rate and serial settings.
- Extended CAN header handling.
- Response parsing.
- ISO-TP multi-frame handling.
- BMS request/response validation.
- A working battery telemetry polling loop.

The goal is to get your 2022 ID.4 reporting real battery data locally, without cloud services, subscription fees, or any ECU coding modifications.