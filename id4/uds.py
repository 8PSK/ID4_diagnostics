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
