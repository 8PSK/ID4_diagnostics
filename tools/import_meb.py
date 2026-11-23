import csv
import json
import re
import argparse

from pathlib import Path


def find_column(row, candidates):
    for key in row:
        normalized = key.lower().strip()

        for candidate in candidates:
            if candidate in normalized:
                return key

    return None


def extract_can_package(value):
    if not value:
        return None

    match = re.search(
        r"0x([0-9a-fA-F]{8})\s+"
        r"((?:[0-9a-fA-F]{2}\s*)+)",
        value
    )

    if not match:
        return None

    return {
        "can_id": int(match.group(1), 16),
        "bytes": [
            int(x, 16)
            for x in match.group(2).split()
        ]
    }


def import_database(source, destination):
    records = []

    with open(
        source,
        encoding="utf-8-sig",
        newline=""
    ) as file:

        sample = file.read(4096)
        file.seek(0)

        delimiter = ";" if sample.count(";") > sample.count(",") else ","

        reader = csv.DictReader(
            file,
            delimiter=delimiter
        )

        for row in reader:
            name_col = find_column(
                row,
                ["popular name", "name"]
            )

            request_col = find_column(
                row,
                ["request package", "request"]
            )

            response_col = find_column(
                row,
                ["response package", "response"]
            )

            calculation_col = find_column(
                row,
                ["calculation", "formula"]
            )

            unit_col = find_column(
                row,
                ["unit"]
            )

            request = extract_can_package(
                row.get(request_col, "")
                if request_col else ""
            )

            response = extract_can_package(
                row.get(response_col, "")
                if response_col else ""
            )

            payload = request["bytes"] if request else []
            did = None

            if len(payload) >= 4 and payload[1] == 0x22:
                did = (payload[2] << 8) | payload[3]

            records.append({
                "name": (
                    row.get(name_col, "")
                    if name_col else ""
                ),
                "unit": (
                    row.get(unit_col, "")
                    if unit_col else ""
                ),
                "did": (
                    f"0x{did:04X}"
                    if did is not None else None
                ),
                "request": request,
                "response": response,
                "formula": (
                    row.get(calculation_col, "")
                    if calculation_col else ""
                ),
                "source_record": row,
                "verified": False,
                "enabled": False
            })

    Path(destination).parent.mkdir(
        parents=True,
        exist_ok=True
    )

    Path(destination).write_text(
        json.dumps(records, indent=2),
        encoding="utf-8"
    )

    print("Imported records:", len(records))
    print("Output:", destination)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument(
        "--output",
        default="data/meb_catalog.json"
    )

    args = parser.parse_args()

    import_database(
        args.source,
        args.output
    )
