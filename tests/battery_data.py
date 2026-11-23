from tests.run_once import main


if __name__ == "__main__":
    raise SystemExit(main(
        "battery_data",
        categories={"battery", "charging", "electrical", "thermal"},
    ))
