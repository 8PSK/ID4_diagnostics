# VW ID.4 telemetry project — expanded real-time version

I'd expand the project beyond battery SOC and temperature into a complete driving dashboard, covering:

- Vehicle speed and driving activity.
- Battery power consumption in kW.
- Instantaneous energy drain in kWh/100 km.
- Battery voltage and current.
- Estimated remaining battery energy.
- Battery temperatures.
- Charging and regenerative braking.
- Estimated driving range.
- 12V battery voltage.
- Motor and drivetrain information.
- Trip energy consumption and efficiency.

One important distinction: some values are read directly from vehicle ECUs, while others are calculated from live measurements. For example, battery drain rate should be calculated from pack voltage and current, rather than relying on an assumed proprietary DID.

I would also make the database support multiple ECUs and multiple signal sources, so you can eventually add motor, ABS, gateway, and charging-system data without redesigning the application.

## 1. Real ID.4 signals from the MEB database

I checked the actual [OBDb Volkswagen ID.4 signal database](<https://github.com/OBDb/Volkswagen-ID.4/blob/main/signalsets/v3/default.json?utm_source=chatgpt.com>) rather than inventing additional DID values.

It contains useful mappings for the 2022 vehicle, including:

| Signal | DID | ECU response address |
| --- | --- | --- |
| Vehicle speed | `F40D` | `17FE007B` |
| Motor RPM | `F40C` | `17FE007B` |
| Display SOC | `028C` | `17FE007B` |
| BMS SOC | `3DEF` | `17FE0076` |
| HV battery voltage | `1E3C` | `17FE007B` |
| HV battery current | `1E3E` | `17FE007B` |
| Battery maximum temperature | `1E0E` | `17FE007B` |
| Battery minimum temperature | `1E0F` | `17FE007B` |
| Maximum cell voltage | `1E33` | `17FE007B` |
| Minimum cell voltage | `1E34` | `17FE007B` |
| Charging current limit | `1E1B` | `17FE007B` |
| Discharging current limit | `1E1C` | `17FE007B` |
| Battery temperature inlet/outlet | `189D` | `17FE007B` |
| Battery energy | `2AB8` | 11-bit ECU profile |

These mappings and conversion definitions are present in the community database. Some other records are restricted to particular model-year ranges, so the importer must preserve those restrictions.

GitHub

+1

Important: The final `2AB8` example uses a different CAN addressing configuration. It should not be mixed into the extended-CAN polling profile without explicitly switching protocols.

## 2. Updated project structure

Keep the original project structure, with these additions:

text

```text
id4-telemetry/
├── config.json
├── requirements.txt
├── main.py
├── id4/
│   ├── __init__.py
│   ├── elm327.py
│   ├── uds.py
│   ├── decoder.py
│   ├── derived.py
│   ├── telemetry.py
│   ├── storage.py
│   └── importer.py
├── tools/
│   ├── probe_elm327.py
│   └── import_meb.py
├── data/
│   ├── signals.json
│   ├── meb_catalog.json
│   └── telemetry.db
└── dashboard/
    ├── __init__.py
    ├── server.py
    └── static/
        └── index.html
```

The files below replace or extend the earlier versions.

## 3. `data/signals.json`

This is the most important update. It includes direct ECU signals, conversion formulas, CAN routing, polling intervals, and signal provenance.

I have included 2022-relevant mappings from OBDb. Signals remain disabled until their response format has been checked against the vehicle.

json

```json

{
  "vehicle": {
    "make": "Volkswagen",
    "model": "ID.4",
    "year": 2022,
    "platform": "MEB"
  },
  "source": {
    "repository": "https://github.com/OBDb/Volkswagen-ID.4",
    "file": "signalsets/v3/default.json",
    "license": "CC-BY-SA-4.0",
    "attribution": "OBDb Volkswagen ID.4 contributors"
  },
  "settings": {
    "can_protocol": "15765-4-29bit",
    "can_bitrate": 500000,
    "current_positive_means_discharge": null,
    "usable_capacity_kwh": null
  },
  "signals": [
    {
      "id": "vehicle_speed",
      "name": "Vehicle speed",
      "category": "movement",
      "ecu": "vehicle",
      "tx_id": "0x17FC007B",
      "rx_id": "0x17FE007B",
      "did": "0xF40D",
      "byte_offset": 0,
      "byte_length": 1,
      "datatype": "uint",
      "multiplier": 1,
      "divisor": 1,
      "offset": 0,
      "unit": "km/h",
      "interval": 1,
      "enabled": false,
      "verified": false
    },
    {
      "id": "motor_rpm",
      "name": "Motor RPM",
      "category": "drivetrain",
      "ecu": "motor",
      "tx_id": "0x17FC007B",
      "rx_id": "0x17FE007B",
      "did": "0xF40C",
      "byte_offset": 0,
      "byte_length": 2,
      "datatype": "uint",
      "multiplier": 1,
      "divisor": 4,
      "offset": 0,
      "unit": "rpm",
      "interval": 1,
      "enabled": false,
      "verified": false
    },
    {
      "id": "battery_soc_display",
      "name": "Displayed battery SOC",
      "category": "battery",
      "ecu": "bms",
      "tx_id": "0x17FC007B",
      "rx_id": "0x17FE007B",
      "did": "0x028C",
      "byte_offset": 0,
      "byte_length": 1,
      "datatype": "uint",
      "multiplier": 20.4,
      "divisor": 46,
      "offset": -6.4,
      "unit": "%",
      "interval": 3,
      "enabled": false,
      "verified": false
    },
    {
      "id": "battery_soc",
      "name": "BMS state of charge",
      "category": "battery",
      "ecu": "bms",
      "tx_id": "0x17FC0076",
      "rx_id": "0x17FE0076",
      "did": "0x3DEF",
      "byte_offset": 0,
      "byte_length": 2,
      "datatype": "int",
      "multiplier": 1,
      "divisor": 100,
      "offset": 0,
      "unit": "%",
      "interval": 3,
      "enabled": false,
      "verified": false
    },
    {
      "id": "battery_voltage",
      "name": "HV battery voltage",
      "category": "battery",
      "ecu": "bms",
      "tx_id": "0x17FC007B",
      "rx_id": "0x17FE007B",
      "did": "0x1E3C",
      "byte_offset": 0,
      "byte_length": 4,
      "datatype": "int",
      "multiplier": 1,
      "divisor": 4096,
      "offset": 0,
      "unit": "V",
      "interval": 1,
      "enabled": false,
      "verified": false
    },
    {
      "id": "battery_current",
      "name": "HV battery current",
      "category": "battery",
      "ecu": "bms",
      "tx_id": "0x17FC007B",
      "rx_id": "0x17FE007B",
      "did": "0x1E3E",
      "byte_offset": 0,
      "byte_length": 4,
      "datatype": "uint",
      "multiplier": 1,
      "divisor": 100,
      "offset": -1500,
      "unit": "A",
      "interval": 1,
      "enabled": false,
      "verified": false,
      "polarity_verified": false
    },
    {
      "id": "battery_temp_max",
      "name": "Maximum battery temperature",
      "category": "battery",
      "ecu": "bms",
      "tx_id": "0x17FC007B",
      "rx_id": "0x17FE007B",
      "did": "0x1E0E",
      "byte_offset": 0,
      "byte_length": 2,
      "datatype": "int",
      "multiplier": 1,
      "divisor": 64,
      "offset": 0,
      "unit": "°C",
      "interval": 5,
      "enabled": false,
      "verified": false
    },
    {
      "id": "battery_temp_min",
      "name": "Minimum battery temperature",
      "category": "battery",
      "ecu": "bms",
      "tx_id": "0x17FC007B",
      "rx_id": "0x17FE007B",
      "did": "0x1E0F",
      "byte_offset": 0,
      "byte_length": 2,
      "datatype": "int",
      "multiplier": 1,
      "divisor": 64,
      "offset": 0,
      "unit": "°C",
      "interval": 5,
      "enabled": false,
      "verified": false
    },
    {
      "id": "battery_temp_inlet",
      "name": "Battery coolant inlet temperature",
      "category": "thermal",
      "ecu": "bms",
      "tx_id": "0x17FC007B",
      "rx_id": "0x17FE007B",
      "did": "0x189D",
      "byte_offset": 2,
      "byte_length": 2,
      "datatype": "int",
      "multiplier": 1,
      "divisor": 64,
      "offset": 0,
      "unit": "°C",
      "interval": 5,
      "enabled": false,
      "verified": false
    },
    {
      "id": "battery_temp_outlet",
      "name": "Battery coolant outlet temperature",
      "category": "thermal",
      "ecu": "bms",
      "tx_id": "0x17FC007B",
      "rx_id": "0x17FE007B",
      "did": "0x189D",
      "byte_offset": 0,
      "byte_length": 2,
      "datatype": "int",
      "multiplier": 1,
      "divisor": 64,
      "offset": 0,
      "unit": "°C",
      "interval": 5,
      "enabled": false,
      "verified": false
    },
    {
      "id": "cell_voltage_max",
      "name": "Maximum cell voltage",
      "category": "battery",
      "ecu": "bms",
      "tx_id": "0x17FC007B",
      "rx_id": "0x17FE007B",
      "did": "0x1E33",
      "byte_offset": 0,
      "byte_length": 2,
      "datatype": "uint",
      "multiplier": 1,
      "divisor": 4096,
      "offset": 0,
      "unit": "V",
      "interval": 5,
      "enabled": false,
      "verified": false
    },
    {
      "id": "cell_voltage_min",
      "name": "Minimum cell voltage",
      "category": "battery",
      "ecu": "bms",
      "tx_id": "0x17FC007B",
      "rx_id": "0x17FE007B",
      "did": "0x1E34",
      "byte_offset": 0,
      "byte_length": 2,
      "datatype": "uint",
      "multiplier": 1,
      "divisor": 4096,
      "offset": 0,
      "unit": "V",
      "interval": 5,
      "enabled": false,
      "verified": false
    },
    {
      "id": "charge_current_limit",
      "name": "Maximum charging current",
      "category": "charging",
      "ecu": "bms",
      "tx_id": "0x17FC007B",
      "rx_id": "0x17FE007B",
      "did": "0x1E1B",
      "byte_offset": 0,
      "byte_length": 2,
      "datatype": "uint",
      "multiplier": 1,
      "divisor": 5,
      "offset": 0,
      "unit": "A",
      "interval": 5,
      "enabled": false,
      "verified": false
    },
    {
      "id": "discharge_current_limit",
      "name": "Maximum discharging current",
      "category": "charging",
      "ecu": "bms",
      "tx_id": "0x17FC007B",
      "rx_id": "0x17FE007B",
      "did": "0x1E1C",
      "byte_offset": 0,
      "byte_length": 2,
      "datatype": "uint",
      "multiplier": 1,
      "divisor": 5,
      "offset": 0,
      "unit": "A",
      "interval": 5,
      "enabled": false,
      "verified": false
    },
    {
      "id": "aux_battery_voltage",
      "name": "12V battery voltage",
      "category": "electrical",
      "ecu": "bms",
      "tx_id": "0x17FC007B",
      "rx_id": "0x17FE007B",
      "did": "0x1E3B",
      "byte_offset": 0,
      "byte_length": 2,
      "datatype": "uint",
      "multiplier": 1,
      "divisor": 4,
      "offset": 0,
      "unit": "V",
      "interval": 10,
      "enabled": false,
      "verified": false
    }
  ]
}
```

A note about the current signal: the source database gives a conversion formula, but the direction convention must be established on your car. The application will not guess whether positive current means charging or discharging.

## 4. `id4/decoder.py`

The new decoder supports the MEB database's conversion format:

- Unsigned and signed integers.
- Multiple bytes.
- Byte offsets.
- Multipliers and divisors.
- Calibration offsets.
- Exact payload length validation.

python

```python

def decode_signal(signal, payload):
    if not signal.get("verified"):
        raise ValueError(
            f"Unverified signal: {signal['id']}"
        )

    byte_offset = signal.get("byte_offset", 0)
    byte_length = signal["byte_length"]

    if byte_length < 1:
        raise ValueError("Invalid byte length")

    end = byte_offset + byte_length

    if len(payload) != end and len(payload) < end:
        raise ValueError(
            f"{signal['id']}: expected at least "
            f"{end} bytes, received {len(payload)}"
        )

    raw_bytes = payload[byte_offset:end]

    raw = int.from_bytes(
        raw_bytes,
        byteorder="big",
        signed=signal["datatype"] == "int"
    )

    multiplier = float(signal.get("multiplier", 1))
    divisor = float(signal.get("divisor", 1))
    offset = float(signal.get("offset", 0))

    if divisor == 0:
        raise ValueError("Divisor cannot be zero")

    value = (raw * multiplier / divisor) + offset

    return {
        "id": signal["id"],
        "name": signal["name"],
        "value": round(value, 4),
        "unit": signal["unit"],
        "raw": raw
    }
```

## 5. `id4/derived.py`

This is where the interesting driving metrics are calculated.

It derives:

- Battery power.
- Instantaneous drain.
- Regenerative power.
- Consumption in kWh/100 km.
- Trip energy.
- Trip distance.
- Average trip efficiency.
- Estimated remaining energy.

python

```python

import time


class DerivedTelemetry:

    def __init__(self, settings):
        self.settings = settings

        self.previous_time = None
        self.trip_energy_kwh = 0.0
        self.trip_distance_km = 0.0

        self.latest = {}

    def calculate(self, signals):

        speed = self.value(signals, "vehicle_speed")
        voltage = self.value(signals, "battery_voltage")
        current = self.value(signals, "battery_current")
        soc = self.value(signals, "battery_soc_display")

        now = time.time()

        result = {
            "vehicle_speed": speed,
            "battery_power_kw": None,
            "battery_drain_kw": None,
            "regenerative_power_kw": None,
            "consumption_kwh_100km": None,
            "remaining_energy_kwh": None,
            "trip_energy_kwh": self.trip_energy_kwh,
            "trip_distance_km": self.trip_distance_km,
            "trip_average_kwh_100km": None,
            "power_direction": "unknown"
        }

        if voltage is not None and current is not None:

            # Electrical power magnitude/sign before
            # applying the vehicle-specific polarity setting.
            raw_power = voltage * current / 1000

            positive_is_discharge = (
                self.settings.get(
                    "current_positive_means_discharge"
                )
            )

            if positive_is_discharge is not None:

                discharge_power = (
                    raw_power
                    if positive_is_discharge
                    else -raw_power
                )

                result["battery_power_kw"] = round(
                    discharge_power, 3
                )

                result["battery_drain_kw"] = round(
                    max(0, discharge_power), 3
                )

                result["regenerative_power_kw"] = round(
                    max(0, -discharge_power), 3
                )

                result["power_direction"] = (
                    "discharge"
                    if discharge_power > 0
                    else "charge_or_regeneration"
                )

                if speed is not None and speed > 5:
                    result["consumption_kwh_100km"] = round(
                        max(0, discharge_power) / speed * 100,
                        2
                    )

                if self.previous_time is not None:
                    dt = min(
                        max(now - self.previous_time, 0),
                        10
                    )

                    self.trip_energy_kwh += (
                        max(0, discharge_power) * dt / 3600
                    )

                    if speed is not None:
                        self.trip_distance_km += (
                            max(0, speed) * dt / 3600
                        )

                self.previous_time = now

        capacity = self.settings.get(
            "usable_capacity_kwh"
        )

        if soc is not None and capacity:
            result["remaining_energy_kwh"] = round(
                capacity * soc / 100,
                2
            )

        if self.trip_distance_km > 0:
            result["trip_average_kwh_100km"] = round(
                self.trip_energy_kwh
                / self.trip_distance_km
                * 100,
                2
            )

        result["trip_energy_kwh"] = round(
            self.trip_energy_kwh, 3
        )

        result["trip_distance_km"] = round(
            self.trip_distance_km, 3
        )

        self.latest = result

        return result

    @staticmethod
    def value(signals, name):
        item = signals.get(name)

        if not item:
            return None

        if item.get("status") != "valid":
            return None

        return item.get("value")
```

Drain-rate interpretation

- `battery_drain_kw`: instantaneous battery discharge power.
- `regenerative_power_kw`: power flowing back into the battery, subject to the configured current polarity.
- `consumption_kwh_100km`: instantaneous consumption normalized by speed.
- `trip_average_kwh_100km`: accumulated trip energy divided by accumulated distance.

The calculation uses pack voltage multiplied by pack current. It is a battery-side measurement, not motor-only consumption. Auxiliary loads therefore contribute when the measured current includes them.

## 6. `id4/telemetry.py`

This version groups signals sharing the same DID, so the two battery coolant temperature measurements require only one request.

python

```python

import asyncio
import json
import time

from collections import defaultdict
from pathlib import Path

from id4.decoder import decode_signal
from id4.uds import UDSClient
from id4.derived import DerivedTelemetry


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

        self.settings = config["settings"]

        self.signals = [
            s for s in config["signals"]
            if s.get("enabled")
            and s.get("verified")
        ]

        self.latest = {}
        self.derived = DerivedTelemetry(
            self.settings
        )

        self.groups = defaultdict(list)

        for signal in self.signals:
            key = (
                signal["tx_id"],
                signal["rx_id"],
                signal["did"]
            )

            self.groups[key].append(signal)

        self.running = False

    async def poll_group(self, key, signals):

        tx_id = int(key[0], 16)
        rx_id = int(key[1], 16)
        did = int(key[2], 16)

        payload = await asyncio.to_thread(
            self.uds.read_data_by_identifier,
            tx_id,
            rx_id,
            did
        )

        for signal in signals:
            decoded = decode_signal(
                signal,
                payload
            )

            decoded["timestamp"] = time.time()
            decoded["status"] = "valid"

            self.latest[signal["id"]] = decoded

            await asyncio.to_thread(
                self.storage.save,
                signal["id"],
                decoded
            )

    async def run(self):

        self.running = True

        intervals = {
            key: min(
                s.get("interval", 5)
                for s in signals
            )
            for key, signals in self.groups.items()
        }

        next_poll = {
            key: 0
            for key in self.groups
        }

        while self.running:

            now = time.monotonic()

            for key, signals in self.groups.items():

                if now < next_poll[key]:
                    continue

                try:
                    await self.poll_group(
                        key,
                        signals
                    )

                except Exception as exc:

                    for signal in signals:
                        self.latest[signal["id"]] = {
                            "id": signal["id"],
                            "name": signal["name"],
                            "status": "error",
                            "error": str(exc),
                            "timestamp": time.time()
                        }

                next_poll[key] = (
                    time.monotonic()
                    + intervals[key]
                )

            derived = self.derived.calculate(
                self.latest
            )

            self.latest["derived"] = {
                "name": "Calculated driving metrics",
                "status": "valid",
                "timestamp": time.time(),
                **derived
            }

            await asyncio.sleep(0.1)

    def stop(self):
        self.running = False
```

This scheduler serializes access to the ELM327, avoiding simultaneous serial requests from different dashboard clients.

## 7. `config.json`

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
    "timeout": 5,
    "protocol": "8"
  },
  "polling": {
    "minimum_interval": 1,
    "default_interval": 5
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

## 8. `dashboard/static/index.html`

The dashboard now has driving, battery, power, and thermal sections.

HTMLWrap linesCopy codePreview

```html

<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport"
      content="width=device-width, initial-scale=1">

<title>VW ID.4 Telemetry</title>

<style>
:root {
  color-scheme: dark;
  font-family: system-ui, sans-serif;
  background: #101720;
  color: #f3f6fa;
}

body {
  max-width: 1300px;
  margin: auto;
  padding: 24px;
}

h1 { font-size: 28px; }

h2 {
  font-size: 19px;
  margin: 30px 0 14px;
}

.status {
  display: inline-block;
  background: #273647;
  padding: 9px 15px;
  border-radius: 20px;
  color: #9db2c8;
  font-size: 13px;
}

.grid {
  display: grid;
  grid-template-columns:
    repeat(auto-fit,minmax(180px,1fr));
  gap: 14px;
}

.card {
  background: #202c3a;
  padding: 19px;
  border-radius: 13px;
  min-height: 90px;
}

.name {
  color: #a5b4c5;
  font-size: 13px;
}

.value {
  font-size: 29px;
  font-weight: 700;
  margin-top: 14px;
}

.unit {
  font-size: 13px;
  color: #a5b4c5;
}

.error {
  color: #ff9a9a;
  font-size: 12px;
  margin-top: 7px;
}

.muted {
  color: #8595a7;
  font-size: 12px;
  margin-top: 8px;
}

.footer {
  margin-top: 35px;
  font-size: 12px;
  color: #8392a2;
}
</style>
</head>

<body>

<h1>Volkswagen ID.4</h1>

<p class="muted">
2022 MEB | Live vehicle and battery telemetry
</p>

<div class="status" id="status">
Connecting...
</div>

<h2>Driving</h2>
<div class="grid" id="driving"></div>

<h2>Battery</h2>
<div class="grid" id="battery"></div>

<h2>Power and efficiency</h2>
<div class="grid" id="power"></div>

<h2>Thermal management</h2>
<div class="grid" id="thermal"></div>

<h2>Drivetrain</h2>
<div class="grid" id="drivetrain"></div>

<h2>Electrical system</h2>
<div class="grid" id="electrical"></div>

<div class="footer">
Local read-only telemetry.
No vehicle coding or control functions.
</div>

<script>
const sections = {
  driving: [
    ["vehicle_speed", "Vehicle speed"],
    ["motor_rpm", "Motor RPM"]
  ],

  battery: [
    ["battery_soc_display", "Displayed SOC"],
    ["battery_soc", "BMS SOC"],
    ["battery_voltage", "HV voltage"],
    ["battery_current", "HV current"],
    ["cell_voltage_max", "Maximum cell voltage"],
    ["cell_voltage_min", "Minimum cell voltage"],
    ["battery_temp_max", "Maximum battery temperature"],
    ["battery_temp_min", "Minimum battery temperature"]
  ],

  power: [
    ["battery_power_kw", "Battery power"],
    ["battery_drain_kw", "Battery drain"],
    ["regenerative_power_kw", "Regenerative power"],
    ["consumption_kwh_100km", "Instant consumption"],
    ["remaining_energy_kwh", "Estimated energy remaining"],
    ["trip_energy_kwh", "Trip energy used"],
    ["trip_distance_km", "Trip distance"],
    ["trip_average_kwh_100km", "Trip average consumption"]
  ],

  thermal: [
    ["battery_temp_inlet", "Coolant inlet"],
    ["battery_temp_outlet", "Coolant outlet"]
  ],

  drivetrain: [
    ["motor_rpm", "Motor speed"]
  ],

  electrical: [
    ["aux_battery_voltage", "12V battery voltage"]
  ]
};

const units = {
  vehicle_speed: "km/h",
  motor_rpm: "rpm",
  battery_soc_display: "%",
  battery_soc: "%",
  battery_voltage: "V",
  battery_current: "A",
  battery_temp_max: "°C",
  battery_temp_min: "°C",
  battery_temp_inlet: "°C",
  battery_temp_outlet: "°C",
  cell_voltage_max: "V",
  cell_voltage_min: "V",
  battery_power_kw: "kW",
  battery_drain_kw: "kW",
  regenerative_power_kw: "kW",
  consumption_kwh_100km: "kWh/100 km",
  remaining_energy_kwh: "kWh",
  trip_energy_kwh: "kWh",
  trip_distance_km: "km",
  trip_average_kwh_100km: "kWh/100 km",
  aux_battery_voltage: "V"
};

function getValue(data, key) {
  if (key in data) {
    return data[key];
  }

  const derived = data.derived;

  if (derived && key in derived) {
    return {
      value: derived[key],
      status: "valid"
    };
  }

  return null;
}

function makeCard(key, label, data) {
  const card = document.createElement("div");
  card.className = "card";

  const name = document.createElement("div");
  name.className = "name";
  name.textContent = label;

  const value = document.createElement("div");
  value.className = "value";

  const item = getValue(data, key);

  if (item && item.status === "valid"
      && item.value !== null
      && item.value !== undefined) {

    value.textContent =
      Number(item.value).toFixed(2);

    const unit = document.createElement("span");
    unit.className = "unit";
    unit.textContent = " " + (units[key] || "");

    value.append(unit);

  } else {
    value.textContent = "--";

    const error = document.createElement("div");
    error.className = "error";

    error.textContent =
      item?.error || "Waiting for verified data";

    card.append(error);
  }

  card.append(name, value);
  return card;
}

function update(data) {
  for (const [section, items] of Object.entries(sections)) {
    const container = document.getElementById(section);
    container.replaceChildren();

    for (const [key, label] of items) {
      container.append(
        makeCard(key, label, data)
      );
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
    document.getElementById("status").textContent =
      "Connected to vehicle telemetry";
  };

  ws.onmessage = event => {
    update(JSON.parse(event.data));
  };

  ws.onclose = () => {
    document.getElementById("status").textContent =
      "Disconnected - reconnecting";

    setTimeout(connect, 3000);
  };

  ws.onerror = () => {
    document.getElementById("status").textContent =
      "Connection error";
  };
}

connect();
</script>

</body>
</html>
```

## 9. `id4/uds.py`

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
        payload = self.transport.read_did(
            tx_id,
            rx_id,
            did
        )

        if not isinstance(payload, bytes):
            raise TypeError("Expected bytes from transport")

        if len(payload) < 3:
            raise ValueError("Incomplete UDS response")

        if payload[0] != 0x62:
            raise ValueError(
                f"Unexpected UDS service: {payload[0]:02X}"
            )

        response_did = int.from_bytes(
            payload[1:3],
            "big"
        )

        if response_did != did:
            raise ValueError(
                f"DID mismatch: expected {did:04X}, "
                f"received {response_did:04X}"
            )

        return payload[3:]
```

## 10. `id4/importer.py`

This imports the original OBDb signal database and preserves its CAN addressing and scaling metadata for further conversion.

python

```python

import json
import urllib.request
from pathlib import Path


SOURCE = (
    "https://raw.githubusercontent.com/"
    "OBDb/Volkswagen-ID.4/main/"
    "signalsets/v3/default.json"
)


def download_database(destination):
    request = urllib.request.Request(
        SOURCE,
        headers={"User-Agent": "ID4-Telemetry/1.0"}
    )

    with urllib.request.urlopen(
        request,
        timeout=30
    ) as response:
        content = response.read()

    data = json.loads(content)

    Path(destination).parent.mkdir(
        parents=True,
        exist_ok=True
    )

    Path(destination).write_text(
        json.dumps(data, indent=2),
        encoding="utf-8"
    )

    print(
        f"Downloaded {len(data.get('commands', []))} "
        "command definitions"
    )


def extract_commands(database, model_year=2022):
    result = []

    for command in database.get("commands", []):

        year_filter = (
            command.get("filter")
            or command.get("dbgfilter")
            or {}
        )

        start = year_filter.get("from")
        end = year_filter.get("to")
        years = year_filter.get("years")

        if years and model_year not in years:
            continue

        if start is not None and model_year < start:
            continue

        if end is not None and model_year > end:
            continue

        result.append(command)

    return result


if __name__ == "__main__":
    download_database(
        "data/meb_catalog.json"
    )

    database = json.loads(
        Path("data/meb_catalog.json").read_text()
    )

    commands = extract_commands(
        database,
        model_year=2022
    )

    print(
        "Commands matching year:",
        len(commands)
    )
```

This importer retains the OBDb command structures rather than treating every command as a simple DID. The OBDb definitions include CAN headers, receive addresses, protocol, frequency, bit positions, and scaling metadata.

GitHub

+1

## 11. Updated `id4/elm327.py`

Use this version to accommodate both ELM327 response formats: responses that retain ISO-TP single-frame PCI bytes and responses where the adapter has already stripped them.

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

    def command(self, cmd, timeout=None):
        self.ser.reset_input_buffer()

        self.ser.write(
            (cmd + "\r").encode("ascii")
        )

        result = bytearray()
        deadline = time.monotonic() + (
            timeout or self.timeout
        )

        while time.monotonic() < deadline:
            result.extend(self.ser.read(256))

            if b">" in result:
                break

        response = result.decode(
            "ascii",
            errors="replace"
        ).replace(">", "").strip()

        upper = response.upper()

        if "?" in upper:
            raise ELM327Error(response)

        if "UNABLE TO CONNECT" in upper:
            raise ELM327Error(response)

        if "STOPPED" in upper:
            raise ELM327Error(response)

        return response

    def initialize(self):

        self.command("ATZ", timeout=8)

        for cmd in (
            "ATE0",
            "ATL0",
            "ATS1",
            "ATH1",
            "ATSP8",
            "ATCAF1",
            "ATCFC1"
        ):
            response = self.command(cmd)

            if "OK" not in response.upper():
                raise ELM327Error(
                    f"Initialization failed: {cmd}"
                )

        protocol = self.command("ATDPN")

        if protocol.strip() not in ("8", "8?"):
            raise ELM327Error(
                f"Expected protocol 8, got {protocol}"
            )

    def configure_ecu(self, tx_id, rx_id):

        if not 0 <= tx_id <= 0x1FFFFFFF:
            raise ValueError("Invalid TX identifier")

        if not 0 <= rx_id <= 0x1FFFFFFF:
            raise ValueError("Invalid RX identifier")

        self.command(f"ATSH{tx_id:08X}")
        self.command(f"ATCRA{rx_id:08X}")

    @staticmethod
    def parse_response(response, expected_rx_id, expected_did):

        for line in response.splitlines():

            line = line.strip().upper()

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

            # Some adapters retain the ISO-TP PCI byte.
            if data[0] >> 4 == 0:

                length = data[0] & 0x0F

                if length > 7 or len(data) < length + 1:
                    raise ELM327Error(
                        "Invalid ISO-TP single frame"
                    )

                payload = data[1:1 + length]

            elif data[0] >> 4 == 1:

                raise ELM327Error(
                    "Multi-frame response detected. "
                    "Not supported by this single-frame driver."
                )

            # Other adapters remove the PCI byte using CAF.
            elif data[0] == 0x62:

                payload = data

            elif data[0] == 0x7F:

                if len(data) >= 3:
                    raise ELM327Error(
                        f"Negative UDS response: "
                        f"service={data[1]:02X}, "
                        f"NRC={data[2]:02X}"
                    )

                raise ELM327Error(
                    "Incomplete negative UDS response"
                )

            else:
                continue

            if len(payload) < 3:
                continue

            if payload[0] != 0x62:
                continue

            did = int.from_bytes(
                payload[1:3],
                "big"
            )

            if did != expected_did:
                raise ELM327Error("Unexpected DID")

            return payload

        raise ELM327Error(
            f"No valid response for DID "
            f"{expected_did:04X}"
        )

    def read_did(self, tx_id, rx_id, did):

        self.configure_ecu(tx_id, rx_id)

        response = self.command(
            f"22{did:04X}"
        )

        return self.parse_response(
            response,
            rx_id,
            did
        )

    def close(self):
        if self.ser.is_open:
            self.ser.close()
```

This parser still does not implement multi-frame reassembly. Also, ELM327 clone formatting varies, so validate it against captured responses before enabling the longer DIDs.

## 12. Updated dashboard API

Your existing `dashboard/server.py` can remain mostly unchanged. The following is the version I recommend using with the new telemetry format.

python

```python

import asyncio
import json

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from id4.elm327 import ELM327Transport
from id4.telemetry import BatteryTelemetry
from id4.storage import TelemetryStorage


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

    adapter = CONFIG["adapter"]
    database = CONFIG["database"]

    transport = ELM327Transport(
        port=adapter["port"],
        baudrate=adapter["baudrate"],
        timeout=adapter["timeout"]
    )

    storage = TelemetryStorage(
        database["sqlite"]
    )

    telemetry = BatteryTelemetry(
        transport,
        database["signals"],
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

        transport.close()
        storage.close()


app = FastAPI(
    title="VW ID.4 Live Telemetry",
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
        "enabled_signals": len(telemetry.signals)
    }


@app.get("/api/telemetry")
async def get_telemetry():
    return telemetry.latest


@app.get("/api/history/{signal}")
async def history(signal: str, limit: int = 100):

    if not 1 <= limit <= 1000:
        return {"error": "Invalid limit"}

    return storage.history(
        signal,
        limit
    )


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
```

## 13. Enable the first real-time signals

After testing the adapter and validating the response parser, edit `data/signals.json`.

For the initial test, I recommend enabling these signals:

json

```json
{
  "id": "vehicle_speed",
  "enabled": true,
  "verified": true
}
```

Apply the same change to:

- `battery_soc_display`
- `battery_soc`
- `battery_voltage`
- `battery_current`
- `motor_rpm`

Keep the other signals disabled until their responses are checked.

For battery current, leave `polarity_verified` false until you establish its direction convention.

In `data/signals.json`, change:

json

```json
"current_positive_means_discharge": null
```

to either `true` or `false` only after comparing the current reading during driving and regenerative braking.

## 14. Install and run

From the project root:

bash

```bash
source .venv/bin/activate

pip install -r requirements.txt

mkdir -p data/raw

python tools/probe_elm327.py \
    --port /dev/ttyUSB0 \
    --baud 38400
```

Import the community database:

bash

```bash
python -c "
from id4.importer import download_database
download_database('data/meb_catalog.json')
"
```

Validate your JSON:

bash

```bash
python -m json.tool data/signals.json > /dev/null
python -m json.tool data/meb_catalog.json > /dev/null
```

Start the application:

bash

```bash
python main.py
```

Open:

[VW ID.4 Live Dashboard](<http://127.0.0.1:8000?utm_source=chatgpt.com>)

## 15. Final dashboard capabilities

## ID.4 Live Telemetry

Proposed dashboard layout — actual values require vehicle connection and signal validation.

Vehicle speed# -- km/h

Battery SOC# --%

Battery power# -- kW

Energy consumption# -- kWh/100 km

Battery condition

- Pack voltage and current
- Maximum/minimum temperature
- Maximum/minimum cell voltage
- Coolant inlet/outlet temperature
- Charge/discharge current limits
- 12V battery voltage
  Driving analytics
- Instantaneous drain rate
- Regenerative braking power
- Motor RPM
- Trip energy consumption
- Trip distance
- Average efficiency
- Remaining energy estimate

## 16. Important hardware and compatibility notes

The original OBDb repository is licensed CC BY-SA 4.0, so retain attribution and observe its share-alike requirements when distributing adapted signal definitions.

OBDb/Volkswagen-ID.4 · GitHub

+1

A few limitations remain:

1. The ELM327 must support extended 29-bit CAN.
2. The current implementation only supports single-frame ISO-TP responses.
3. Battery current polarity must be calibrated.
4. The 2022 vehicle's software and battery configuration must be checked.
5. The 12V, thermal and cell signals must be verified individually.
6. The trip accumulator currently has no trip-reset or ignition-cycle detection.

My recommendation: Prioritize speed, SOC, pack voltage, pack current, and motor RPM. Those five measurements give us the foundation for a genuinely useful live driving dashboard. Once they work reliably, add cell health, thermal management, charging and regenerative braking.

The next major improvement should be a proper multi-frame ISO-TP implementation and an automated importer that converts the entire OBDb MEB signal set into your application's normalized database, preserving all ECU addresses, bit positions, year filters and scaling formulas.