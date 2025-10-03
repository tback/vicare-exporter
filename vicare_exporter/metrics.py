import functools
import logging
import signal
import time
from datetime import datetime
from threading import Event
from typing import Optional, Union

from prometheus_client import Enum, Gauge
from PyViCare.PyViCare import PyViCare
from PyViCare.PyViCareUtils import PyViCareInternalServerError, PyViCareRateLimitError

from .enums import _ENUMS

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


@functools.cache
def get_metric_for_name(
    name: str, labels: tuple[str], unit: str, type_: str
) -> Optional[Union[Gauge, Enum]]:
    log.debug("Getting metric for: %s", name)
    documentation, states = _ENUMS.get(name, (None, None))
    if documentation:
        return Enum(
            name,
            documentation=documentation,
            states=states,
            labelnames=labels,
        )

    unit = UNITS.get(unit, unit)
    if name.endswith("_status") and type_ == "string":
        return Enum(
            name, "Status", states=["error", "connected", "ok"], labelnames=labels
        )
    elif type_ in ("number", "boolean"):
        return Gauge(name, name, labelnames=labels, unit=unit)
    else:
        log.warning("Skipping metric: %s", name)
        return None


def extract_feature_metrics(feature: dict, installation_id: str):
    properties = feature.get("properties")

    labels = dict(
        gateway_id=feature["gatewayId"],
        device_id=feature.get("deviceId", "none"),
        installation_id=installation_id,
    )

    # check if this is a heating circuit/burners metric
    component_id, label_name, metric_name = _extract_component_id(feature["feature"])
    if component_id is not None:
        labels[label_name] = component_id

    label_names = tuple(sorted(labels))
    for property_name in PROPERTY_NAMES:
        if property_name not in properties:
            continue

        prop = properties[property_name]
        value = prop["value"]
        # pick only the current day as metric
        if property_name == "day":
            value = value[0]

        # map on/off to true/false
        elif property_name == "status" and value in ("on", "off"):
            property_name = "on"
            value = value == "on"

        name = "_".join((metric_name, property_name))
        metric = get_metric_for_name(
            name, label_names, unit=prop.get("unit"), type_=prop["type"]
        )
        if isinstance(metric, Gauge):
            metric.labels(**labels).set(value)
        elif isinstance(metric, Enum):
            if value not in metric._states and value.lower() in metric._states:
                value = value.lower()
            if value not in metric._states:
                log.warning("Unknown state for enum: %s: %s", name, value)
            metric.labels(**labels).state(value)


class ViCareExporter:
    def __init__(self, vicare: PyViCare, ignore_devices: list[str]):
        self.vicare = vicare
        self.ignore_devices = ignore_devices or []

    def _fetch_devices_features(self) -> int:
        n_features = 0
        for device in self.vicare.devices:
            if device.device_id in self.ignore_devices:
                log.debug(f"Skipping device: {device.device_id}")
                continue

            features = device.service.fetch_all_features()
            for feature in features.get("data", []):
                extract_feature_metrics(
                    feature, installation_id=device.service.accessor.id
                )
                n_features += 1

        return n_features

    def poll(self):
        t = time.time()

        try:
            n_features = self._fetch_devices_features()
        except PyViCareInternalServerError:
            log.error(
                "An ViCare internal error occurred",
                exc_info=True,
            )
        else:
            log.info(f"Fetched {n_features} features in {time.time() - t:g} seconds")

    def poll_forever(self, sleep=120):
        stop_event = Event()

        def do_stop(signum, _):
            log.info("Received signal %s - stopping.", signum)
            stop_event.set()

        signal.signal(signal.SIGINT, do_stop)
        signal.signal(signal.SIGTERM, do_stop)
        while not stop_event.is_set():
            try:
                self.poll()
            except PyViCareRateLimitError as err:
                log.error(err.message)
                log.error("Waiting until rate limit reset.")
                stop_event.wait((err.limitResetDate - datetime.now()).total_seconds())

            stop_event.wait(sleep)
