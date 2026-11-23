# One-shot read-only data tests

## Windows

Run these commands from the project root:

```powershell
python -m tests.all_data --port COM3
python -m tests.battery_data --port COM3
python -m tests.driving_data --port COM3
```

## Ubuntu Linux

From the project root, create and activate a virtual environment, install the
project dependencies, then run the tests using your adapter's serial device:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m tests.all_data --port /dev/ttyUSB0
python -m tests.battery_data --port /dev/ttyUSB0
python -m tests.driving_data --port /dev/ttyUSB0
```

The adapter may instead appear as `/dev/ttyACM0`. If permission is denied,
add your user to the `dialout` group with `sudo usermod -aG dialout "$USER"`,
then log out and back in.

Omit `--port` to use the configured adapter port. Each command reads once and
writes a CSV file to `tests/results` named
`YYYYMMDD_HHMMSS_[all_data|battery_data|driving_data].csv`. The same values,
skips, and errors are printed to the terminal. Use `--config`, `--baud`, or
`--output-dir` to override the corresponding defaults.

Only signals marked both `enabled` and `verified` in the configured signal
database are requested. Other selected signals are reported as skipped, and
the adapter is not opened if there are no eligible signals. Requests use the
project's UDS ReadDataByIdentifier service (`0x22`) only; this is read-only
and is distinct from standard OBD-II Mode 02 freeze-frame requests.

The battery test includes `battery`, `charging`, `electrical`, and `thermal`
categories. The driving test includes `movement` and `drivetrain`.
