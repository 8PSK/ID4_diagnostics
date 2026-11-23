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

    if len(payload) < end:
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
