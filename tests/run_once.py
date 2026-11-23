import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from id4.decoder import decode_signal
from id4.elm327 import ELM327Error, ELM327Transport
from id4.uds import UDSClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_FIELDS = (
    "timestamp",
    "signal_id",
    "name",
    "category",
    "value",
    "unit",
    "raw",
    "status",
    "error",
)


def _read_selected_signals(signals, transport):
    eligible = [
        signal
        for signal in signals
        if signal.get("enabled") and signal.get("verified")
    ]
    rows = []

    for signal in signals:
        if signal in eligible:
            continue

        rows.append({
            "signal_id": signal.get("id", ""),
            "name": signal.get("name", ""),
            "category": signal.get("category", ""),
            "status": "skipped",
            "error": (
                "Signal must be both enabled and verified "
                f"(enabled={bool(signal.get('enabled'))}, "
                f"verified={bool(signal.get('verified'))})"
            ),
        })

    groups = defaultdict(list)
    for signal in eligible:
        key = (signal["tx_id"], signal["rx_id"], signal["did"])
        groups[key].append(signal)

    uds = UDSClient(transport)
    for (tx_id, rx_id, did), grouped_signals in groups.items():
        try:
            payload = uds.read_data_by_identifier(
                int(tx_id, 16),
                int(rx_id, 16),
                int(did, 16),
            )
        except (ELM327Error, OSError, TypeError, ValueError) as exc:
            for signal in grouped_signals:
                rows.append({
                    "signal_id": signal["id"],
                    "name": signal["name"],
                    "category": signal.get("category", ""),
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                })
            continue

        for signal in grouped_signals:
            try:
                decoded = decode_signal(signal, payload)
            except (KeyError, TypeError, ValueError) as exc:
                rows.append({
                    "signal_id": signal["id"],
                    "name": signal["name"],
                    "category": signal.get("category", ""),
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                })
                continue

            rows.append({
                "signal_id": decoded["id"],
                "name": decoded["name"],
                "category": signal.get("category", ""),
                "value": decoded["value"],
                "unit": decoded["unit"],
                "raw": decoded["raw"],
                "status": "valid",
                "error": "",
            })

    return rows


def _load_test_data(config_path, categories):
    config_path = Path(config_path)
    if not config_path.is_absolute():
        config_path = PROJECT_ROOT / config_path

    config = json.loads(config_path.read_text(encoding="utf-8"))
    signals_path = Path(config["database"]["signals"])
    if not signals_path.is_absolute():
        signals_path = config_path.parent / signals_path

    database = json.loads(signals_path.read_text(encoding="utf-8"))
    signals = database["signals"]
    if categories is not None:
        signals = [
            signal
            for signal in signals
            if signal.get("category") in categories
        ]

    return config, signals


def run_once(
    test_name,
    categories,
    config_path="config.json",
    output_dir=None,
    port=None,
    baud=None,
    transport_factory=ELM327Transport,
):
    config, signals = _load_test_data(config_path, categories)
    output_dir = Path(output_dir or PROJECT_ROOT / "tests" / "results")
    if not output_dir.is_absolute():
        output_dir = PROJECT_ROOT / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
    adapter = config["adapter"]
    eligible = [
        signal
        for signal in signals
        if signal.get("enabled") and signal.get("verified")
    ]
    rows = []

    if eligible:
        transport = None
        try:
            transport = transport_factory(
                port=port or adapter["port"],
                baudrate=baud or adapter["baudrate"],
                timeout=adapter["timeout"],
            )
            rows = _read_selected_signals(signals, transport)
        except (ELM327Error, OSError, TypeError, ValueError) as exc:
            message = f"{type(exc).__name__}: {exc}"
            print(f"Adapter/read setup failed: {message}")
            rows = [
                {
                    "signal_id": signal.get("id", ""),
                    "name": signal.get("name", ""),
                    "category": signal.get("category", ""),
                    "status": (
                        "error"
                        if signal.get("enabled") and signal.get("verified")
                        else "skipped"
                    ),
                    "error": (
                        message
                        if signal.get("enabled") and signal.get("verified")
                        else "Signal must be both enabled and verified"
                    ),
                }
                for signal in signals
            ]
        finally:
            if transport is not None:
                transport.close()
    else:
        rows = [
            {
                "signal_id": signal.get("id", ""),
                "name": signal.get("name", ""),
                "category": signal.get("category", ""),
                "status": "skipped",
                "error": (
                    "Signal must be both enabled and verified "
                    f"(enabled={bool(signal.get('enabled'))}, "
                    f"verified={bool(signal.get('verified'))})"
                ),
            }
            for signal in signals
        ]

    for row in rows:
        row["timestamp"] = timestamp

    filename = (
        f"{datetime.now().astimezone():%Y%m%d_%H%M%S}_{test_name}.csv"
    )
    csv_path = output_dir / filename
    with csv_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n{test_name}:")
    if not rows:
        print("No signals matched this test.")
    for row in rows:
        value = row.get("value", "")
        unit = row.get("unit", "")
        print(
            f"{row.get('signal_id', '')}: {value} {unit} "
            f"[{row['status']}]"
            + (f" - {row['error']}" if row.get("error") else "")
        )
    print(f"CSV saved to: {csv_path}")

    if not eligible or any(row["status"] == "error" for row in rows):
        return 1
    return 0


def main(test_name, categories):
    parser = argparse.ArgumentParser(
        description=(
            "Read selected enabled and verified vehicle signals once "
            "using UDS ReadDataByIdentifier (service 0x22)."
        )
    )
    parser.add_argument(
        "--config",
        default=str(PROJECT_ROOT / "config.json"),
        help="Path to the project configuration JSON",
    )
    parser.add_argument(
        "--port",
        help="Serial port override, for example COM3 on Windows",
    )
    parser.add_argument("--baud", type=int, help="Serial baud-rate override")
    parser.add_argument(
        "--output-dir",
        help="Directory for timestamped CSV output",
    )
    args = parser.parse_args()

    return run_once(
        test_name,
        categories,
        config_path=args.config,
        output_dir=args.output_dir,
        port=args.port,
        baud=args.baud,
    )
