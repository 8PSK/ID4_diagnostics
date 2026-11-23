import sqlite3
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
