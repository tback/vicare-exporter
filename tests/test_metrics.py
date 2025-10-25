import json
import logging
import sys
import typing
from pathlib import Path

import pytest
from prometheus_client.exposition import generate_latest
from prometheus_client.registry import CollectorRegistry

from vicare_exporter.metrics import LOGGER, ViCareCollector, _extract_component_id


@pytest.fixture(scope="session", autouse=True)
def _debug_log():
    logging.basicConfig(
        format="%(asctime)s :: %(name)s :: %(message)s", level="INFO", stream=sys.stdout
    )
    LOGGER.setLevel("DEBUG")


@pytest.mark.parametrize(
    ["feature", "label", "component_id", "name"],
    [
        (
            "heating.circuits.0.operating.programs.active",
            "circuits_id",
            "0",
            "heating_circuits_operating_programs_active",
        ),
        (
            "heating.burners.0.modulation",
            "burners_id",
            "0",
            "heating_burners_modulation",
        ),
        (
            "heating.burners.10.modulation",
            "burners_id",
            "10",
            "heating_burners_modulation",
        ),
    ],
)
def test_component_id_extractor(feature: str, label: str, component_id: str, name: str):
    feature_id, feature_label, feature_name = _extract_component_id(feature)
    assert feature_id == component_id
    assert feature_label == label
    assert feature_name == name


tests_folder = Path(__file__).parent
data_paths = sorted((tests_folder / "data").glob("*_data.json"))


def _find_feature(
    feature: str, property: str, devices_data: dict[str, dict[str, typing.Any]]
) -> float:
    for data in devices_data.values():
        for datapoint in data["data"]:
            if datapoint["feature"] == feature:
                value = datapoint["properties"][property]["value"]
                if isinstance(value, list):
                    return value[0]
                else:
                    return value

    raise KeyError(f"No feature {feature} in {devices_data}")


CHECKS = {
    "heating_solar_sensors_temperature_dhw_value_celsius": (
        "heating.solar.sensors.temperature.dhw",
        "value",
    ),
    "heating_solar_sensors_temperature_collector_value_celsius": (
        "heating.solar.sensors.temperature.collector",
        "value",
    ),
    "heating_power_consumption_total_day_kWh": (
        "heating.power.consumption.total",
        "day",
    ),
    "heating_dhw_sensors_temperature_hotWaterStorage_value_celsius": (
        "heating.dhw.sensors.temperature.hotWaterStorage",
        "value",
    ),
    "heating_burners_automatic_status": ("heating.burners.0.automatic", "status"),
    "heating_burners_modulation_value_percent": (
        "heating.burners.0.modulation",
        "value",
    ),
    "heating_boiler_temperature_value_celsius": ("heating.boiler.temperature", "value"),
    "heating_dhw_sensors_temperature_dhwCylinder_value_celsius": (
        "heating.dhw.sensors.temperature.dhwCylinder",
        "value",
    ),
    "heating_dhw_sensors_temperature_dhwCylinder_status": (
        "heating.dhw.sensors.temperature.dhwCylinder",
        "status",
    ),
}


@pytest.mark.parametrize("data_file", data_paths, ids=[dp.stem for dp in data_paths])
def test_data(data_file: str):
    with open(data_file, "r") as fp:
        test_data = json.load(fp)

    collector = ViCareCollector(vicare=None, ignore_devices=[])
    registry = CollectorRegistry()
    registry.register(collector)

    def mock_fetch():
        return test_data

    collector._fetch_features = mock_fetch
    prom_out = generate_latest(registry).decode("utf-8")
    print(prom_out)

    metric_values = {}
    for m in collector.collect():
        metric_values[m.name] = m.samples[0].labels.get("value", m.samples[0].value)

    for metric_name, (feature, prop) in CHECKS.items():
        assert metric_values[metric_name] == _find_feature(feature, prop, test_data)
