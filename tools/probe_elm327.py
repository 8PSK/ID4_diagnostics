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
                print(f"{cmd:10} -> {response}")

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
