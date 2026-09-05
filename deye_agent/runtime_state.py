import copy
import datetime
import threading
import time
from collections import deque


HEALTH_SCHEMA = "deye-agent.health.v1"
OVERVIEW_SCHEMA = "deye-agent.overview.v1"
HISTORY_SCHEMA = "deye-agent.history.v1"


HISTORY_METRIC_MAP = (
    ("grid_power_w", "grid.power_w"),
    ("load_power_w", "load.power_w"),
    ("inverter_power_w", "inverter.output_power_w"),
    ("pv_power_w", "pv.total_power_w"),
    ("battery_power_w", "battery.power_w"),
    ("battery_soc_percent", "battery.soc_percent"),
    ("grid_voltage_v", "grid.voltage_v"),
    ("grid_frequency_hz", "grid.frequency_hz"),
    ("inverter_voltage_v", "inverter.output_voltage_v"),
    ("battery_voltage_v", "battery.voltage_v"),
)


def _utc_now_iso():
    """Return a compact UTC timestamp compatible with Python 3.6."""
    return (
        datetime.datetime.utcnow()
        .replace(microsecond=0)
        .isoformat()
        + "Z"
    )


def _metric_value(metrics, metric_id):
    """Return one normalized metric value or None when unavailable."""
    if not isinstance(metrics, dict):
        return None

    metric = metrics.get(metric_id)

    if not isinstance(metric, dict):
        return None

    if not metric.get("available", False):
        return None

    return metric.get("value")


class RuntimeState:
    """Thread-safe runtime cache and bounded in-memory history.

    This class has no serial, Modbus, MQTT or notification dependencies.
    It only receives already normalized polling-cycle documents.
    """

    def __init__(
            self,
            profile_name,
            mqtt_enabled=False,
            mqtt_metrics_enabled=False,
            http_api_enabled=False,
            history_enabled=True,
            history_max_samples=720,
            history_retention_seconds=21600):
        self._lock = threading.RLock()
        self._profile_name = profile_name
        self._mqtt_enabled = bool(mqtt_enabled)
        self._mqtt_metrics_enabled = bool(mqtt_metrics_enabled)
        self._http_api_enabled = bool(http_api_enabled)

        self._history_enabled = bool(history_enabled)

        try:
            history_max_samples = int(history_max_samples)
        except (TypeError, ValueError):
            history_max_samples = 720

        if history_max_samples < 2:
            history_max_samples = 2

        try:
            history_retention_seconds = int(history_retention_seconds)
        except (TypeError, ValueError):
            history_retention_seconds = 21600

        if history_retention_seconds < 60:
            history_retention_seconds = 60

        self._history_max_samples = history_max_samples
        self._history_retention_seconds = history_retention_seconds
        self._history = deque(maxlen=history_max_samples)

        self._snapshot = None
        self._metrics = None
        self._last_update = None
        self._last_update_monotonic = None
        self._last_successful_update = None
        self._generation = 0

    def _build_history_sample(
            self,
            timestamp,
            monotonic_timestamp,
            generation,
            metrics_document):
        metrics = (
            metrics_document.get("metrics", {})
            if isinstance(metrics_document, dict)
            else {}
        )

        sample = {
            "timestamp": timestamp,
            "_monotonic": monotonic_timestamp,
            "generation": generation,
        }

        for field_name, metric_id in HISTORY_METRIC_MAP:
            sample[field_name] = _metric_value(
                metrics,
                metric_id
            )

        return sample

    def _purge_history_locked(self, now_monotonic):
        cutoff = (
            now_monotonic
            - self._history_retention_seconds
        )

        while (
                self._history
                and self._history[0]["_monotonic"] < cutoff):
            self._history.popleft()

    def update_cycle(self, snapshot, metrics):
        """Store one completed acquisition result atomically."""
        if snapshot is None and metrics is None:
            return

        now_iso = _utc_now_iso()
        now_monotonic = time.monotonic()

        snapshot_copy = copy.deepcopy(snapshot)
        metrics_copy = copy.deepcopy(metrics)

        with self._lock:
            self._snapshot = snapshot_copy
            self._metrics = metrics_copy
            self._last_update = now_iso
            self._last_update_monotonic = now_monotonic
            self._generation += 1

            summary = (
                snapshot_copy.get("summary", {})
                if isinstance(snapshot_copy, dict)
                else {}
            )

            if summary.get("status") == "ok":
                self._last_successful_update = now_iso

            if self._history_enabled:
                self._history.append(
                    self._build_history_sample(
                        now_iso,
                        now_monotonic,
                        self._generation,
                        metrics_copy
                    )
                )
                self._purge_history_locked(
                    now_monotonic
                )

    def _age_seconds_locked(self):
        if self._last_update_monotonic is None:
            return None

        return round(
            max(
                0.0,
                time.monotonic()
                - self._last_update_monotonic
            ),
            3
        )

    def get_snapshot(self):
        with self._lock:
            return copy.deepcopy(self._snapshot)

    def get_metrics(self):
        with self._lock:
            return copy.deepcopy(self._metrics)

    def get_health(self):
        with self._lock:
            snapshot = self._snapshot
            metrics = self._metrics

            snapshot_summary = (
                snapshot.get("summary", {})
                if isinstance(snapshot, dict)
                else {}
            )
            metrics_summary = (
                metrics.get("summary", {})
                if isinstance(metrics, dict)
                else {}
            )
            device_info = (
                snapshot.get("device_info", {})
                if isinstance(snapshot, dict)
                else {}
            )

            status = snapshot_summary.get("status") or "starting"

            return {
                "schema": HEALTH_SCHEMA,
                "schema_version": 1,
                "read_only": True,
                "status": status,
                "profile": self._profile_name,
                "device": {
                    "serial_number": device_info.get(
                        "serial_number"
                    ),
                    "rated_power_w": device_info.get(
                        "rated_power_w"
                    ),
                },
                "acquisition": {
                    "last_update": self._last_update,
                    "last_successful_update": (
                        self._last_successful_update
                    ),
                    "age_seconds": self._age_seconds_locked(),
                    "snapshot_status": snapshot_summary.get(
                        "status"
                    ),
                    "snapshot_complete": snapshot_summary.get(
                        "complete"
                    ),
                },
                "metrics": {
                    "total": metrics_summary.get(
                        "metrics_total"
                    ),
                    "available": metrics_summary.get(
                        "metrics_available"
                    ),
                    "unavailable": metrics_summary.get(
                        "metrics_unavailable"
                    ),
                },
                "services": {
                    "mqtt_enabled": self._mqtt_enabled,
                    "mqtt_metrics_enabled": (
                        self._mqtt_metrics_enabled
                    ),
                    "http_api_enabled": (
                        self._http_api_enabled
                    ),
                    "history_enabled": (
                        self._history_enabled
                    ),
                },
            }

    def get_overview(self):
        """Return one compact UI view from one cache generation."""
        with self._lock:
            snapshot = self._snapshot
            metrics_document = self._metrics

            if not isinstance(snapshot, dict):
                return None

            if not isinstance(metrics_document, dict):
                return None

            metrics = metrics_document.get("metrics")

            if not isinstance(metrics, dict):
                return None

            snapshot_summary = snapshot.get("summary", {})
            metrics_summary = metrics_document.get("summary", {})

            snapshot_status = snapshot_summary.get("status")
            metrics_status = metrics_summary.get("status")

            status = (
                snapshot_status
                or metrics_status
                or "unknown"
            )
            complete = bool(
                snapshot_summary.get("complete")
                and metrics_summary.get("complete")
            )

            return {
                "schema": OVERVIEW_SCHEMA,
                "schema_version": 1,
                "read_only": True,
                "profile": self._profile_name,
                "generation": self._generation,
                "status": status,
                "complete": complete,
                "acquisition": {
                    "last_update": self._last_update,
                    "last_successful_update": (
                        self._last_successful_update
                    ),
                    "age_seconds": self._age_seconds_locked(),
                    "snapshot_status": snapshot_status,
                    "metrics_status": metrics_status,
                },
                "device": {
                    "serial_number": _metric_value(
                        metrics, "device.serial_number"
                    ),
                    "type": _metric_value(
                        metrics, "device.type"
                    ),
                    "rated_power_w": _metric_value(
                        metrics, "device.rated_power_w"
                    ),
                    "protocol_version": _metric_value(
                        metrics, "device.protocol_version"
                    ),
                    "mppt_count": _metric_value(
                        metrics, "device.mppt_count"
                    ),
                    "phase_count": _metric_value(
                        metrics, "device.phase_count"
                    ),
                },
                "operating_status": {
                    "run_state": _metric_value(
                        metrics, "status.run_state"
                    ),
                    "has_warning": _metric_value(
                        metrics, "status.has_warning"
                    ),
                    "has_fault": _metric_value(
                        metrics, "status.has_fault"
                    ),
                    "sd_card": _metric_value(
                        metrics, "status.sd_card"
                    ),
                },
                "grid": {
                    "voltage_v": _metric_value(
                        metrics, "grid.voltage_v"
                    ),
                    "frequency_hz": _metric_value(
                        metrics, "grid.frequency_hz"
                    ),
                    "current_a": _metric_value(
                        metrics, "grid.current_a"
                    ),
                    "power_w": _metric_value(
                        metrics, "grid.power_w"
                    ),
                    "relay_status": _metric_value(
                        metrics, "grid.relay_status"
                    ),
                    "relay_closed": _metric_value(
                        metrics, "grid.relay_closed"
                    ),
                },
                "inverter": {
                    "output_power_w": _metric_value(
                        metrics,
                        "inverter.output_power_w"
                    ),
                    "output_voltage_v": _metric_value(
                        metrics,
                        "inverter.output_voltage_v"
                    ),
                    "output_frequency_hz": _metric_value(
                        metrics,
                        "inverter.output_frequency_hz"
                    ),
                    "igbt_temperature_c": _metric_value(
                        metrics,
                        "inverter.igbt_temperature_c"
                    ),
                },
                "load": {
                    "power_w": _metric_value(
                        metrics, "load.power_w"
                    ),
                    "current_a": _metric_value(
                        metrics, "load.current_a"
                    ),
                    "frequency_hz": _metric_value(
                        metrics, "load.frequency_hz"
                    ),
                },
                "pv": {
                    "total_power_w": _metric_value(
                        metrics, "pv.total_power_w"
                    ),
                    "pv1": {
                        "voltage_v": _metric_value(
                            metrics, "pv.1.voltage_v"
                        ),
                        "current_a": _metric_value(
                            metrics, "pv.1.current_a"
                        ),
                        "power_w": _metric_value(
                            metrics, "pv.1.power_w"
                        ),
                    },
                    "pv2": {
                        "voltage_v": _metric_value(
                            metrics, "pv.2.voltage_v"
                        ),
                        "current_a": _metric_value(
                            metrics, "pv.2.current_a"
                        ),
                        "power_w": _metric_value(
                            metrics, "pv.2.power_w"
                        ),
                    },
                },
                "battery": {
                    "voltage_v": _metric_value(
                        metrics, "battery.voltage_v"
                    ),
                    "current_a": _metric_value(
                        metrics, "battery.current_a"
                    ),
                    "power_w": _metric_value(
                        metrics, "battery.power_w"
                    ),
                    "soc_percent": _metric_value(
                        metrics, "battery.soc_percent"
                    ),
                    "temperature_c": _metric_value(
                        metrics, "battery.temperature_c"
                    ),
                    "capacity_ah": _metric_value(
                        metrics,
                        "battery.corrected_capacity_ah"
                    ),
                    "bms": {
                        "soc_percent": _metric_value(
                            metrics,
                            "battery.bms.soc_percent"
                        ),
                        "realtime_voltage_v": _metric_value(
                            metrics,
                            "battery.bms.realtime_voltage_v"
                        ),
                        "realtime_current_a": _metric_value(
                            metrics,
                            "battery.bms.realtime_current_a"
                        ),
                        "temperature_c": _metric_value(
                            metrics,
                            "battery.bms.temperature_c"
                        ),
                        "alarm_present": _metric_value(
                            metrics,
                            "battery.bms.alarm_present"
                        ),
                        "fault_present": _metric_value(
                            metrics,
                            "battery.bms.fault_present"
                        ),
                        "type": _metric_value(
                            metrics,
                            "battery.bms.type"
                        ),
                    },
                },
                "energy_today": {
                    "pv_kwh": _metric_value(
                        metrics, "energy.pv.today_kwh"
                    ),
                    "grid_buy_kwh": _metric_value(
                        metrics,
                        "energy.grid.buy.today_kwh"
                    ),
                    "grid_sell_kwh": _metric_value(
                        metrics,
                        "energy.grid.sell.today_kwh"
                    ),
                    "load_kwh": _metric_value(
                        metrics, "energy.load.today_kwh"
                    ),
                    "battery_charge_kwh": _metric_value(
                        metrics,
                        "energy.battery.charge.today_kwh"
                    ),
                    "battery_discharge_kwh": _metric_value(
                        metrics,
                        "energy.battery.discharge.today_kwh"
                    ),
                    "generator_kwh": _metric_value(
                        metrics,
                        "energy.generator.today_kwh"
                    ),
                },
                "generator": {
                    "relay_status": _metric_value(
                        metrics,
                        "generator.relay_status"
                    ),
                    "switch_signal": _metric_value(
                        metrics,
                        "generator.switch_signal"
                    ),
                    "frequency_hz": _metric_value(
                        metrics,
                        "generator.frequency_hz"
                    ),
                },
                "configuration": {
                    "maximum_grid_power_w": _metric_value(
                        metrics,
                        "config.maximum_grid_power_w"
                    ),
                    "solar_sell_enabled": _metric_value(
                        metrics,
                        "config.solar_sell_enabled"
                    ),
                    "time_of_use_enabled": _metric_value(
                        metrics,
                        "config.time_of_use_enabled"
                    ),
                },
                "quality": {
                    "metrics_total": metrics_summary.get(
                        "metrics_total"
                    ),
                    "metrics_available": metrics_summary.get(
                        "metrics_available"
                    ),
                    "metrics_unavailable": metrics_summary.get(
                        "metrics_unavailable"
                    ),
                },
                "services": {
                    "mqtt_enabled": self._mqtt_enabled,
                    "mqtt_metrics_enabled": (
                        self._mqtt_metrics_enabled
                    ),
                    "http_api_enabled": (
                        self._http_api_enabled
                    ),
                    "history_enabled": (
                        self._history_enabled
                    ),
                },
            }

    def get_history(self, minutes=60):
        """Return chart-friendly samples from bounded in-memory history."""
        try:
            minutes = int(minutes)
        except (TypeError, ValueError):
            raise ValueError("minutes must be an integer")

        if minutes < 1:
            raise ValueError("minutes must be at least 1")

        now_monotonic = time.monotonic()
        cutoff = now_monotonic - (minutes * 60)

        with self._lock:
            self._purge_history_locked(now_monotonic)

            samples = []

            for stored in self._history:
                if stored["_monotonic"] < cutoff:
                    continue

                sample = dict(stored)
                sample.pop("_monotonic", None)
                samples.append(sample)

            return {
                "schema": HISTORY_SCHEMA,
                "schema_version": 1,
                "read_only": True,
                "profile": self._profile_name,
                "generation": self._generation,
                "requested_minutes": minutes,
                "retention_seconds": (
                    self._history_retention_seconds
                ),
                "max_samples": self._history_max_samples,
                "sample_count": len(samples),
                "samples": samples,
            }
