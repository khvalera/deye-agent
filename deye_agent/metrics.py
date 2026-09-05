METRICS_SCHEMA = "deye-agent.metrics.v1"


# Metric IDs are an API contract. Keep existing IDs stable once published.
#
# Definitions intentionally include only fields with established semantics.
# Revision-sensitive raw ranges and disputed/undecoded fields are excluded.
_DIRECT_METRICS = (
    # Device metadata / capability.
    (
        "device.serial_number",
        ("device_info", "serial_number"),
        None,
        "info",
    ),
    (
        "device.type",
        ("device_info", "device_type"),
        None,
        "info",
    ),
    (
        "device.protocol_version",
        ("device_info", "protocol_version"),
        None,
        "info",
    ),
    (
        "device.rated_power_w",
        ("device_info", "rated_power_w"),
        "W",
        "gauge",
    ),
    (
        "device.mppt_count",
        ("device_info", "mppt_count"),
        None,
        "info",
    ),
    (
        "device.phase_count",
        ("device_info", "phase_count"),
        None,
        "info",
    ),

    # Operational status.
    (
        "status.run_state",
        ("telemetry", "Run State"),
        None,
        "status",
    ),
    (
        "status.sd_card",
        ("telemetry", "SD Card Status"),
        None,
        "status",
    ),
    (
        "status.has_warning",
        ("telemetry", "Has Warning"),
        None,
        "status",
    ),
    (
        "status.warning_word_1",
        ("telemetry", "Warning Word 1"),
        None,
        "status_code",
    ),
    (
        "status.warning_word_2",
        ("telemetry", "Warning Word 2"),
        None,
        "status_code",
    ),
    (
        "status.has_fault",
        ("telemetry", "Has Fault"),
        None,
        "status",
    ),
    (
        "status.fault_word_1",
        ("telemetry", "Fault Word 1"),
        None,
        "status_code",
    ),
    (
        "status.fault_word_2",
        ("telemetry", "Fault Word 2"),
        None,
        "status_code",
    ),
    (
        "status.fault_word_3",
        ("telemetry", "Fault Word 3"),
        None,
        "status_code",
    ),
    (
        "status.fault_word_4",
        ("telemetry", "Fault Word 4"),
        None,
        "status_code",
    ),

    # Grid.
    (
        "grid.voltage_v",
        ("telemetry", "Grid Voltage"),
        "V",
        "gauge",
    ),
    (
        "grid.frequency_hz",
        ("telemetry", "Grid Frequency"),
        "Hz",
        "gauge",
    ),
    (
        "grid.current_a",
        ("telemetry", "Grid Current"),
        "A",
        "gauge",
    ),
    (
        "grid.power_w",
        ("telemetry", "Grid Power"),
        "W",
        "gauge",
    ),
    (
        "grid.relay_status",
        ("telemetry", "Grid Relay Status"),
        None,
        "status",
    ),

    # Inverter / load.
    (
        "inverter.output_power_w",
        ("telemetry", "Inverter Output Power"),
        "W",
        "gauge",
    ),
    (
        "inverter.output_voltage_v",
        ("telemetry", "Inverter Output Voltage"),
        "V",
        "gauge",
    ),
    (
        "inverter.output_frequency_hz",
        ("telemetry", "Inverter Output Frequency"),
        "Hz",
        "gauge",
    ),
    (
        "inverter.igbt_temperature_c",
        ("telemetry", "IGBT Temperature"),
        "C",
        "gauge",
    ),
    (
        "load.power_w",
        ("telemetry", "Load Power"),
        "W",
        "gauge",
    ),
    (
        "load.current_a",
        ("telemetry", "Load Current"),
        "A",
        "gauge",
    ),
    (
        "load.frequency_hz",
        ("telemetry", "Load Frequency"),
        "Hz",
        "gauge",
    ),

    # PV channels.
    (
        "pv.1.voltage_v",
        ("telemetry", "PV1 Voltage"),
        "V",
        "gauge",
    ),
    (
        "pv.1.current_a",
        ("telemetry", "PV1 Current"),
        "A",
        "gauge",
    ),
    (
        "pv.1.power_w",
        ("telemetry", "PV1 Power"),
        "W",
        "gauge",
    ),
    (
        "pv.2.voltage_v",
        ("telemetry", "PV2 Voltage"),
        "V",
        "gauge",
    ),
    (
        "pv.2.current_a",
        ("telemetry", "PV2 Current"),
        "A",
        "gauge",
    ),
    (
        "pv.2.power_w",
        ("telemetry", "PV2 Power"),
        "W",
        "gauge",
    ),

    # Primary battery telemetry.
    (
        "battery.temperature_c",
        ("telemetry", "Battery Temperature"),
        "C",
        "gauge",
    ),
    (
        "battery.voltage_v",
        ("telemetry", "Battery Voltage"),
        "V",
        "gauge",
    ),
    (
        "battery.current_a",
        ("telemetry", "Battery Current"),
        "A",
        "gauge",
    ),
    (
        "battery.power_w",
        ("telemetry", "Battery Power"),
        "W",
        "gauge",
    ),
    (
        "battery.soc_percent",
        ("telemetry", "Battery Capacity"),
        "%",
        "gauge",
    ),
    (
        "battery.corrected_capacity_ah",
        ("telemetry", "Battery Corrected Capacity"),
        "Ah",
        "gauge",
    ),

    # BMS data is explicitly namespaced so it is never confused with the
    # higher-resolution primary telemetry fields above.
    (
        "battery.bms.charge_voltage_limit_v",
        ("battery", "charging_voltage_v"),
        "V",
        "gauge",
    ),
    (
        "battery.bms.discharge_voltage_limit_v",
        ("battery", "discharge_voltage_v"),
        "V",
        "gauge",
    ),
    (
        "battery.bms.charge_current_limit_a",
        ("battery", "charging_current_limit_a"),
        "A",
        "gauge",
    ),
    (
        "battery.bms.discharge_current_limit_a",
        ("battery", "discharge_current_limit_a"),
        "A",
        "gauge",
    ),
    (
        "battery.bms.soc_percent",
        ("battery", "capacity_percent"),
        "%",
        "gauge",
    ),
    (
        "battery.bms.realtime_voltage_v",
        ("battery", "realtime_voltage_v"),
        "V",
        "gauge",
    ),
    (
        "battery.bms.realtime_current_a",
        ("battery", "realtime_current_a"),
        "A",
        "gauge",
    ),
    (
        "battery.bms.temperature_c",
        ("battery", "realtime_temperature_c"),
        "C",
        "gauge",
    ),
    (
        "battery.bms.max_charge_current_limit_a",
        ("battery", "maximum_charge_current_limit_a"),
        "A",
        "gauge",
    ),
    (
        "battery.bms.max_discharge_current_limit_a",
        ("battery", "maximum_discharge_current_limit_a"),
        "A",
        "gauge",
    ),
    (
        "battery.bms.alarm_present",
        ("battery", "alarm_nonzero"),
        None,
        "status",
    ),
    (
        "battery.bms.fault_present",
        ("battery", "fault_location_nonzero"),
        None,
        "status",
    ),
    (
        "battery.bms.type_code",
        ("battery", "battery_type_code"),
        None,
        "info",
    ),
    (
        "battery.bms.type",
        ("battery", "battery_type"),
        None,
        "info",
    ),

    # Generator.
    (
        "generator.relay_status",
        ("telemetry", "Generator Relay Status"),
        None,
        "status",
    ),
    (
        "generator.switch_signal",
        ("telemetry", "Generator Switch Signal"),
        None,
        "status",
    ),
    (
        "generator.frequency_hz",
        ("telemetry", "Generator Frequency"),
        "Hz",
        "gauge",
    ),
    (
        "generator.operating_time_today_h",
        ("telemetry", "Generator Operating Time Today"),
        "h",
        "counter",
    ),

    # Energy counters.
    (
        "energy.pv.today_kwh",
        ("telemetry", "PV Energy Today"),
        "kWh",
        "counter",
    ),
    (
        "energy.pv.year_kwh",
        ("telemetry", "PV Energy Year"),
        "kWh",
        "counter",
    ),
    (
        "energy.grid.buy.today_kwh",
        ("telemetry", "Grid Buy Energy Today"),
        "kWh",
        "counter",
    ),
    (
        "energy.grid.buy.total_kwh",
        ("telemetry", "Grid Buy Energy Total"),
        "kWh",
        "counter",
    ),
    (
        "energy.grid.sell.today_kwh",
        ("telemetry", "Grid Sell Energy Today"),
        "kWh",
        "counter",
    ),
    (
        "energy.grid.sell.total_kwh",
        ("telemetry", "Grid Sell Energy Total"),
        "kWh",
        "counter",
    ),
    (
        "energy.load.today_kwh",
        ("telemetry", "Load Energy Today"),
        "kWh",
        "counter",
    ),
    (
        "energy.load.total_kwh",
        ("telemetry", "Load Energy Total"),
        "kWh",
        "counter",
    ),
    (
        "energy.load.year_kwh",
        ("telemetry", "Load Energy Year"),
        "kWh",
        "counter",
    ),
    (
        "energy.battery.charge.today_kwh",
        ("telemetry", "Battery Charge Energy Today"),
        "kWh",
        "counter",
    ),
    (
        "energy.battery.charge.total_kwh",
        ("telemetry", "Battery Charge Energy Total"),
        "kWh",
        "counter",
    ),
    (
        "energy.battery.discharge.today_kwh",
        ("telemetry", "Battery Discharge Energy Today"),
        "kWh",
        "counter",
    ),
    (
        "energy.battery.discharge.total_kwh",
        ("telemetry", "Battery Discharge Energy Total"),
        "kWh",
        "counter",
    ),
    (
        "energy.generator.today_kwh",
        ("telemetry", "Generator Energy Today"),
        "kWh",
        "counter",
    ),
    (
        "energy.generator.total_kwh",
        ("telemetry", "Generator Energy Total"),
        "kWh",
        "counter",
    ),

    # High-confidence configuration values useful to UI/API consumers.
    (
        "config.maximum_grid_power_w",
        ("settings", "maximum_grid_power_w"),
        "W",
        "configuration",
    ),
    (
        "config.solar_sell_enabled",
        ("settings", "solar_sell", "enabled"),
        None,
        "configuration",
    ),
    (
        "config.time_of_use_enabled",
        ("settings", "time_of_use", "enabled"),
        None,
        "configuration",
    ),
    (
        "config.battery.max_charge_current_a",
        (
            "settings",
            "battery_configuration",
            "max_charge_current_a",
        ),
        "A",
        "configuration",
    ),
    (
        "config.battery.max_discharge_current_a",
        (
            "settings",
            "battery_configuration",
            "max_discharge_current_a",
        ),
        "A",
        "configuration",
    ),
    (
        "config.grid.voltage_high_v",
        ("settings", "grid", "voltage_high_v"),
        "V",
        "configuration",
    ),
    (
        "config.grid.voltage_low_v",
        ("settings", "grid", "voltage_low_v"),
        "V",
        "configuration",
    ),
    (
        "config.grid.frequency_high_hz",
        ("settings", "grid", "frequency_high_hz"),
        "Hz",
        "configuration",
    ),
    (
        "config.grid.frequency_low_hz",
        ("settings", "grid", "frequency_low_hz"),
        "Hz",
        "configuration",
    ),

    # Validated parallel/system status.
    (
        "system.parallel.enabled",
        ("system", "parallel", "parallel_enabled"),
        None,
        "status",
    ),
    (
        "system.parallel.modbus_sn",
        ("system", "parallel", "modbus_sn"),
        None,
        "info",
    ),
    (
        "system.parallel.a_phase_inverter_count",
        ("system", "parallel", "a_phase_inverter_count"),
        None,
        "gauge",
    ),
    (
        "system.parallel.b_phase_inverter_count",
        ("system", "parallel", "b_phase_inverter_count"),
        None,
        "gauge",
    ),
    (
        "system.parallel.c_phase_inverter_count",
        ("system", "parallel", "c_phase_inverter_count"),
        None,
        "gauge",
    ),
)


def _value_type(value):
    if value is None:
        return None

    if isinstance(value, bool):
        return "boolean"

    if isinstance(value, (int, float)):
        return "number"

    if isinstance(value, str):
        return "string"

    return "object"


def _read_path(root, path):
    current = root

    for key in path:
        if not isinstance(current, dict):
            return None, False

        if key not in current:
            return None, False

        current = current[key]

    return current, True


def _direct_metric(snapshot, metric_id, path, unit, kind):
    value, present = _read_path(snapshot, path)
    available = present and value is not None

    return {
        "value": value if available else None,
        "available": available,
        "unit": unit,
        "value_type": _value_type(value) if available else None,
        "kind": kind,
        "derived": False,
        "source_path": list(path),
    }


def _derived_pv_total(metrics):
    pv1 = metrics["pv.1.power_w"]
    pv2 = metrics["pv.2.power_w"]

    available = pv1["available"] and pv2["available"]

    value = None
    if available:
        value = pv1["value"] + pv2["value"]

    return {
        "value": value,
        "available": available,
        "unit": "W",
        "value_type": "number" if available else None,
        "kind": "gauge",
        "derived": True,
        "source_metric_ids": [
            "pv.1.power_w",
            "pv.2.power_w",
        ],
        "operation": "sum",
    }


def _derived_grid_relay_closed(metrics):
    source = metrics["grid.relay_status"]
    available = source["available"]

    value = None
    if available:
        value = source["value"] == "Closed"

    return {
        "value": value,
        "available": available,
        "unit": None,
        "value_type": "boolean" if available else None,
        "kind": "status",
        "derived": True,
        "source_metric_ids": [
            "grid.relay_status",
        ],
        "operation": "equals_closed",
    }


def _metrics_summary(metrics):
    total = len(metrics)
    available = sum(
        1
        for item in metrics.values()
        if item["available"]
    )
    unavailable = total - available

    if available == 0:
        status = "error"
    elif unavailable:
        status = "partial"
    else:
        status = "ok"

    return {
        "status": status,
        "complete": unavailable == 0,
        "metrics_total": total,
        "metrics_available": available,
        "metrics_unavailable": unavailable,
    }


def build_metrics_from_snapshot(snapshot):
    """Normalize one deye-agent.snapshot.v1 object to stable metric IDs.

    This function performs no hardware access and contains no Modbus register
    addresses. It is intentionally an API-normalization layer above snapshot.
    """
    if not isinstance(snapshot, dict):
        raise ValueError("snapshot must be a dictionary")

    if snapshot.get("schema") != "deye-agent.snapshot.v1":
        raise ValueError(
            "metrics v1 requires deye-agent.snapshot.v1 input"
        )

    metrics = {}

    for metric_id, path, unit, kind in _DIRECT_METRICS:
        if metric_id in metrics:
            raise RuntimeError(
                "duplicate metric ID '{}'".format(metric_id)
            )

        metrics[metric_id] = _direct_metric(
            snapshot,
            metric_id,
            path,
            unit,
            kind
        )

    metrics["pv.total_power_w"] = _derived_pv_total(metrics)
    metrics["grid.relay_closed"] = _derived_grid_relay_closed(metrics)

    summary = _metrics_summary(metrics)

    source_summary = snapshot.get("summary") or {}
    source_acquisition = snapshot.get("acquisition") or {}

    return {
        "schema": METRICS_SCHEMA,
        "schema_version": 1,
        "read_only": True,
        "profile": snapshot.get("profile"),
        "source_snapshot": {
            "schema": snapshot.get("schema"),
            "schema_version": snapshot.get("schema_version"),
            "status": source_summary.get("status"),
            "complete": source_summary.get("complete"),
            "acquisition": source_acquisition,
        },
        "summary": summary,
        "metrics": metrics,
    }


def read_metrics(
        config,
        str_to_bool,
        registers_file,
        profile_name):
    """Read one hardware snapshot and normalize it to metrics v1."""
    from .snapshot import read_snapshot

    snapshot = read_snapshot(
        config,
        str_to_bool,
        registers_file,
        profile_name
    )

    return build_metrics_from_snapshot(snapshot)
