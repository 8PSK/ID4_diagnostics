from tests.run_once import main


if __name__ == "__main__":
    raise SystemExit(main(
        "driving_data",
        categories={"movement", "drivetrain"},
    ))
