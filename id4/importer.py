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
    download_database("data/meb_catalog.json")

    database = json.loads(
        Path("data/meb_catalog.json").read_text()
    )

    commands = extract_commands(
        database,
        model_year=2022
    )

    print("Commands matching year:", len(commands))
