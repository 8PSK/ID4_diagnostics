import asyncio
import json
import time

from collections import defaultdict
from pathlib import Path

from id4.uds import UDSClient
from id4.decoder import decode_signal
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
        self.derived = DerivedTelemetry(self.settings)

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
            decoded = decode_signal(signal, payload)
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
                    await self.poll_group(key, signals)

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

            derived = self.derived.calculate(self.latest)
            self.latest["derived"] = {
                "name": "Calculated driving metrics",
                "status": "valid",
                "timestamp": time.time(),
                **derived
            }

            await asyncio.sleep(0.1)

    def stop(self):
        self.running = False
