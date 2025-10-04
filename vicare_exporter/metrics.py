import datetime
import logging
import time
from typing import Any, Iterable, Optional

from prometheus_client.core import Metric
from prometheus_client.metrics_core import GaugeMetricFamily
from prometheus_client.registry import Collector
from PyViCare.PyViCare import PyViCare

log = logging.getLogger("vicare_exporter")

UNITS = {"kilowattHour": "kWh"}
PROPERTY_NAMES = [
    "active",
    "currentDay",
    "day",
    "hours",
    "shift",
    "slope",
    "starts",
    "status",
    "temperature",
    "value",
]


def _extract_component_id(feature_name) -> tuple[Optional[str], Optional[str], str]:
    parts = feature_name.split(".")
    prev = parts[0]
    for i, part in enumerate(parts[1:], start=1):
        if part.isdigit():
            component_id = part
            label = prev + "_id"
            name = "_".join(parts[:i] + parts[i + 1 :])
            return component_id, label, name
        prev = part

    return None, None, "_".join(parts)


class ViCareCollector(Collector):
    def __init__(
        self,
        vicare: PyViCare,
        ignore_devices: list[str],
        min_fetch_interval_seconds: int = 300,
    ):
        self.vicare = vicare
        self.ignore_devices = ignore_devices or []
        self._data = None
        self._last_fetch = 0
        self.min_fetch_interval_seconds = min_fetch_interval_seconds

    def collect(self) -> Iterable[Metric]:
        n_features = 0
        for installation_id, features in self._fetch_features().items():
            for feature in features.get("data", []):
                yield from self._extract_feature_metrics(
                    feature, installation_id=installation_id
                )
                n_features += 1

        return n_features

    def _extract_feature_metrics(
        self, feature: dict, installation_id: str
    ) -> Iterable[GaugeMetricFamily]:
        properties = feature.get("properties")

        # check if this is a heating circuit/burners or other "enumerated" metric
        # and extract a label for that
        component_id, component_label, metric_name = _extract_component_id(
            feature["feature"]
        )

        for property_name in PROPERTY_NAMES:
            if property_name not in properties:
                continue

            labels = dict(
                gateway_id=feature["gatewayId"],
                device_id=feature.get("deviceId", "none"),
                installation_id=installation_id,
            )
            if component_label:
                labels[component_label] = component_id

            prop = properties[property_name]
            value = prop["value"]
            unit = UNITS.get(prop.get("unit"), prop.get("unit"))

            # pick only the current day as metric
            if property_name == "day":
                value = value[0]

            name = "_".join((metric_name, property_name))

            if isinstance(value, str):
                labels["value"] = value
                value = 1

            metric_family = GaugeMetricFamily(
                name, name, labels=list(labels), unit=unit
            )
            metric_family.add_metric(list(labels.values()), value)
            yield metric_family

    def _fetch_features(self) -> dict[str, dict[str, Any]]:
        now = time.time()

        if (
            self._data is None
            or (now - self._last_fetch) > self.min_fetch_interval_seconds
        ):
            log.info("Fetching metrics")
            self._last_fetch = now
            self._data = {
                str(device.service.accessor.id): device.service.fetch_all_features()
                for device in self.vicare.devices
                if device.device_id not in self.ignore_devices
            }
        else:
            log.debug(
                "Yielding metrics cached at %s",
                datetime.datetime.fromtimestamp(self._last_fetch),
            )

        return self._data
