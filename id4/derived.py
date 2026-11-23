import time


class DerivedTelemetry:

    def __init__(self, settings):
        self.settings = settings
        self.previous_time = None
        self.trip_energy_kwh = 0.0
        self.trip_distance_km = 0.0
        self.latest = {}

    def calculate(self, signals):
        speed = self.value(signals, "vehicle_speed")
        voltage = self.value(signals, "battery_voltage")
        current = self.value(signals, "battery_current")
        soc = self.value(signals, "battery_soc")
        if soc is None:
            soc = self.value(signals, "battery_soc_display")

        now = time.time()
        result = {
            "vehicle_speed": speed,
            "battery_power_kw": None,
            "battery_drain_kw": None,
            "regenerative_power_kw": None,
            "consumption_kwh_100km": None,
            "remaining_energy_kwh": None,
            "trip_energy_kwh": self.trip_energy_kwh,
            "trip_distance_km": self.trip_distance_km,
            "trip_average_kwh_100km": None,
            "power_direction": "unknown"
        }

        if voltage is not None and current is not None:
            raw_power = voltage * current / 1000
            positive_is_discharge = self.settings.get(
                "current_positive_means_discharge"
            )

            if positive_is_discharge is not None:
                discharge_power = (
                    raw_power
                    if positive_is_discharge
                    else -raw_power
                )

                result["battery_power_kw"] = round(discharge_power, 3)
                result["battery_drain_kw"] = round(
                    max(0, discharge_power), 3
                )
                result["regenerative_power_kw"] = round(
                    max(0, -discharge_power), 3
                )
                result["power_direction"] = (
                    "discharge"
                    if discharge_power > 0
                    else "charge_or_regeneration"
                )

                if speed is not None and speed > 5:
                    result["consumption_kwh_100km"] = round(
                        max(0, discharge_power) / speed * 100,
                        2
                    )

                if self.previous_time is not None:
                    dt = min(
                        max(now - self.previous_time, 0),
                        10
                    )
                    self.trip_energy_kwh += (
                        max(0, discharge_power) * dt / 3600
                    )
                    if speed is not None:
                        self.trip_distance_km += (
                            max(0, speed) * dt / 3600
                        )

                self.previous_time = now

        capacity = self.settings.get("usable_capacity_kwh")

        if soc is not None and capacity:
            result["remaining_energy_kwh"] = round(
                capacity * soc / 100,
                2
            )

        if self.trip_distance_km > 0:
            result["trip_average_kwh_100km"] = round(
                self.trip_energy_kwh
                / self.trip_distance_km
                * 100,
                2
            )

        result["trip_energy_kwh"] = round(
            self.trip_energy_kwh, 3
        )
        result["trip_distance_km"] = round(
            self.trip_distance_km, 3
        )
        self.latest = result

        return result

    @staticmethod
    def value(signals, name):
        item = signals.get(name)

        if not item or item.get("status") != "valid":
            return None

        return item.get("value")
