import json
import uvicorn

from pathlib import Path


def main():
    config = json.loads(
        Path("config.json").read_text()
    )

    uvicorn.run(
        "dashboard.server:app",
        host=config["dashboard"]["host"],
        port=config["dashboard"]["port"],
        reload=False
    )


if __name__ == "__main__":
    main()
