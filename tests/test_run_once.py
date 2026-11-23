import csv
import json
import tempfile
import unittest
from pathlib import Path

from tests.run_once import run_once


class FakeTransport:
    def __init__(self, payloads):
        self.payloads = payloads
        self.requests = []
        self.closed = False

    def read_did(self, tx_id, rx_id, did):
        self.requests.append((tx_id, rx_id, did))
        payload = self.payloads[did]
        if isinstance(payload, Exception):
            raise payload
        return payload

    def close(self):
        self.closed = True


class OneShotTest(unittest.TestCase):
    def _transport_factory(self, transport):
        def create(**kwargs):
            self.assertEqual(kwargs["port"], "COM3")
            return transport

        return create

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.signal_path = self.root / "signals.json"
        self.config_path = self.root / "config.json"
        self.output_dir = self.root / "output"
        self.signals = [
            {
                "id": "battery_soc",
                "name": "Battery SOC",
                "category": "battery",
                "tx_id": "0x100",
                "rx_id": "0x101",
                "did": "0x1234",
                "byte_offset": 0,
                "byte_length": 1,
                "datatype": "uint",
                "unit": "%",
                "enabled": True,
                "verified": True,
            },
            {
                "id": "battery_soc_copy",
                "name": "Battery SOC copy",
                "category": "battery",
                "tx_id": "0x100",
                "rx_id": "0x101",
                "did": "0x1234",
                "byte_offset": 1,
                "byte_length": 1,
                "datatype": "uint",
                "unit": "%",
                "enabled": True,
                "verified": True,
            },
            {
                "id": "vehicle_speed",
                "name": "Vehicle speed",
                "category": "movement",
                "tx_id": "0x100",
                "rx_id": "0x101",
                "did": "0x2345",
                "byte_offset": 0,
                "byte_length": 1,
                "datatype": "uint",
                "unit": "km/h",
                "enabled": True,
                "verified": True,
            },
            {
                "id": "unverified",
                "name": "Unverified",
                "category": "battery",
                "tx_id": "0x100",
                "rx_id": "0x101",
                "did": "0x3456",
                "byte_offset": 0,
                "byte_length": 1,
                "datatype": "uint",
                "unit": "x",
                "enabled": True,
                "verified": False,
            },
        ]
        self.signal_path.write_text(
            json.dumps({"signals": self.signals}),
            encoding="utf-8",
        )
        self.config_path.write_text(
            json.dumps({
                "database": {"signals": "signals.json"},
                "adapter": {
                    "port": "COM3",
                    "baudrate": 38400,
                    "timeout": 1,
                },
            }),
            encoding="utf-8",
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_reads_all_once_per_did_and_writes_results(self):
        transport = FakeTransport({
            0x1234: b"\x62\x12\x34\x32\x31",
            0x2345: b"\x62\x23\x45\x28",
        })

        result = run_once(
            "all_data",
            categories=None,
            config_path=self.config_path,
            output_dir=self.output_dir,
            transport_factory=self._transport_factory(transport),
        )

        self.assertEqual(result, 0)
        self.assertEqual(
            transport.requests,
            [(0x100, 0x101, 0x1234), (0x100, 0x101, 0x2345)],
        )
        self.assertTrue(transport.closed)
        csv_path = next(self.output_dir.glob("*_all_data.csv"))
        self.assertRegex(
            csv_path.name,
            r"^\d{8}_\d{6}_all_data\.csv$",
        )
        with csv_path.open(encoding="utf-8", newline="") as file:
            rows = list(csv.DictReader(file))
        self.assertEqual(
            [row["signal_id"] for row in rows],
            [
                "unverified",
                "battery_soc",
                "battery_soc_copy",
                "vehicle_speed",
            ],
        )
        self.assertEqual(rows[0]["status"], "skipped")
        self.assertEqual(rows[1]["value"], "50.0")
        self.assertEqual(rows[2]["value"], "49.0")

    def test_category_selection_does_not_read_other_categories(self):
        transport = FakeTransport({
            0x1234: b"\x62\x12\x34\x32\x31",
        })

        result = run_once(
            "battery_data",
            categories={"battery"},
            config_path=self.config_path,
            output_dir=self.output_dir,
            transport_factory=self._transport_factory(transport),
        )

        self.assertEqual(result, 0)
        self.assertEqual(transport.requests, [(0x100, 0x101, 0x1234)])
        csv_path = next(self.output_dir.glob("*_battery_data.csv"))
        with csv_path.open(encoding="utf-8", newline="") as file:
            rows = list(csv.DictReader(file))
        self.assertNotIn("vehicle_speed", [row["signal_id"] for row in rows])

    def test_records_failed_did_and_continues_reading(self):
        transport = FakeTransport({
            0x1234: OSError("no response"),
            0x2345: b"\x62\x23\x45\x28",
        })

        result = run_once(
            "all_data",
            categories=None,
            config_path=self.config_path,
            output_dir=self.output_dir,
            transport_factory=self._transport_factory(transport),
        )

        self.assertEqual(result, 1)
        csv_path = next(self.output_dir.glob("*_all_data.csv"))
        with csv_path.open(encoding="utf-8", newline="") as file:
            rows = list(csv.DictReader(file))
        statuses = {row["signal_id"]: row["status"] for row in rows}
        self.assertEqual(statuses["battery_soc"], "error")
        self.assertEqual(statuses["vehicle_speed"], "valid")
        self.assertEqual(len(transport.requests), 2)

    def test_does_not_open_adapter_when_no_signal_is_eligible(self):
        for signal in self.signals:
            signal["enabled"] = False
        self.signal_path.write_text(
            json.dumps({"signals": self.signals}),
            encoding="utf-8",
        )

        def unexpected_transport(**_kwargs):
            self.fail(
                f"Adapter should not open without eligible signals: {_kwargs}"
            )

        result = run_once(
            "all_data",
            categories=None,
            config_path=self.config_path,
            output_dir=self.output_dir,
            transport_factory=unexpected_transport,
        )

        self.assertEqual(result, 1)
        csv_path = next(self.output_dir.glob("*_all_data.csv"))
        with csv_path.open(encoding="utf-8", newline="") as file:
            rows = list(csv.DictReader(file))
        self.assertTrue(all(row["status"] == "skipped" for row in rows))


if __name__ == "__main__":
    unittest.main()
