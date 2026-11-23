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
        self.ser.write((command + "\r").encode("ascii"))

        result = bytearray()
        deadline = time.monotonic() + (timeout or self.timeout)

        while time.monotonic() < deadline:
            chunk = self.ser.read(256)

            if chunk:
                result.extend(chunk)

                if b">" in result:
                    break

        response = result.decode("ascii", errors="replace")
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
    def parse_response(response, expected_rx_id, expected_did):
        for line in response.splitlines():
            line = line.strip().upper()

            if not line:
                continue

            if any(
                x in line
                for x in ("SEARCHING", "NO DATA", "BUS INIT", "OK")
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

            if data[0] >> 4 == 0:
                length = data[0] & 0x0F

                if length > 7 or len(data) < length + 1:
                    raise ELM327Error(
                        "Invalid ISO-TP single frame"
                    )

                payload = data[1:1 + length]

            elif data[0] >> 4 == 1:
                raise ELM327Error(
                    "Multi-frame ISO-TP response detected. "
                    "Not supported by this single-frame driver."
                )

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

            did = int.from_bytes(payload[1:3], "big")

            if did != expected_did:
                raise ELM327Error("Unexpected DID")

            return payload

        raise ELM327Error(
            f"No valid response for DID "
            f"{expected_did:04X}"
        )

    def read_did(self, tx_id, rx_id, did):
        if not 0 <= did <= 0xFFFF:
            raise ValueError("Invalid DID")

        self.configure_ecu(tx_id, rx_id)

        response = self.command(f"22{did:04X}")

        return self.parse_response(
            response,
            rx_id,
            did
        )

    def close(self):
        if self.ser and self.ser.is_open:
            self.ser.close()
