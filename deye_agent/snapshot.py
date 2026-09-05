import contextlib
import io


SNAPSHOT_SCHEMA = "deye-agent.snapshot.v1"


def _capture_reader_call(reader):
    """Run one existing reader without allowing stray stdout into JSON.

    Existing readers are expected to stay quiet when DEBUG is false. This
    capture is defensive: legacy error paths may still print a message.

    Returns:
        (data, error_text, captured_lines)
    """
    output = io.StringIO()

    try:
        with contextlib.redirect_stdout(output):
            data = reader()
    except Exception as exc:
        captured = [
            line
            for line in output.getvalue().splitlines()
            if line.strip()
        ]
        return None, str(exc), captured

    captured = [
        line
        for line in output.getvalue().splitlines()
        if line.strip()
    ]

    return data, None, captured


def _base_section_status(error=None, warnings=None):
    return {
        "status": "error" if error else "ok",
        "error": error,
        "warnings": list(warnings or []),
    }


def _evaluate_device_info(data, error, warnings):
    status = _base_section_status(error, warnings)

    if error is None and not data:
        status["status"] = "error"
        status["error"] = "device info returned no data"

    return status


def _evaluate_telemetry(data, error, warnings):
    status = _base_section_status(error, warnings)

    if error is not None:
        return status

    if not data:
        status["status"] = "error"
        status["error"] = "telemetry returned no data"
        status["missing_fields"] = []
        return status

    missing = [
        name
        for name, value in data.items()
        if value is None
    ]

    status["missing_fields"] = missing

    if missing:
        status["status"] = "partial"

    return status


def _evaluate_battery(data, error, warnings):
    status = _base_section_status(error, warnings)

    if error is None and not data:
        status["status"] = "error"
        status["error"] = "battery information returned no data"

    return status


def _evaluate_settings(data, error, warnings):
    status = _base_section_status(error, warnings)

    if error is not None:
        return status

    if not data:
        status["status"] = "error"
        status["error"] = "settings returned no data"
        return status

    grid_support = data.get("grid_support_configuration")

    if (
            isinstance(grid_support, dict)
            and grid_support.get("available") is False):
        status["status"] = "partial"
        status["partial_reason"] = (
            "extended grid-support settings are unavailable"
        )

    return status


def _evaluate_system(data, error, warnings):
    status = _base_section_status(error, warnings)

    if error is None and not data:
        status["status"] = "error"
        status["error"] = "system status returned no data"

    return status


def _snapshot_summary(section_status):
    statuses = [
        item["status"]
        for item in section_status.values()
    ]

    ok_count = statuses.count("ok")
    partial_count = statuses.count("partial")
    error_count = statuses.count("error")

    if error_count == len(statuses):
        overall = "error"
    elif partial_count or error_count:
        overall = "partial"
    else:
        overall = "ok"

    return {
        "status": overall,
        "complete": overall == "ok",
        "sections_total": len(statuses),
        "sections_ok": ok_count,
        "sections_partial": partial_count,
        "sections_error": error_count,
    }


def build_snapshot_from_results(
        profile_name,
        section_results,
        acquisition_mode,
        shared_serial_session):
    """Build the stable snapshot-v1 JSON object from section results."""
    evaluators = {
        "device_info": _evaluate_device_info,
        "telemetry": _evaluate_telemetry,
        "battery": _evaluate_battery,
        "settings": _evaluate_settings,
        "system": _evaluate_system,
    }

    data = {}
    section_status = {}

    for name in (
            "device_info",
            "telemetry",
            "battery",
            "settings",
            "system"):
        result = section_results.get(name) or {}
        section_data = result.get("data")
        error = result.get("error")
        warnings = result.get("warnings") or []

        section_status[name] = evaluators[name](
            section_data,
            error,
            warnings
        )
        data[name] = section_data

    summary = _snapshot_summary(section_status)

    return {
        "schema": SNAPSHOT_SCHEMA,
        "schema_version": 1,
        "read_only": True,
        "profile": profile_name,
        "acquisition": {
            "mode": acquisition_mode,
            "shared_serial_session": bool(shared_serial_session),
            "side_effects": {
                "mqtt_publish": False,
                "alarm_notifications": False,
            },
        },
        "summary": summary,
        "section_status": section_status,
        "device_info": data["device_info"],
        "telemetry": data["telemetry"],
        "battery": data["battery"],
        "settings": data["settings"],
        "system": data["system"],
    }


def build_snapshot_from_readers(
        profile_name,
        device_info_reader,
        telemetry_reader,
        battery_reader,
        settings_reader,
        system_reader):
    """Compatibility builder for independent existing reader calls."""
    definitions = (
        ("device_info", device_info_reader),
        ("telemetry", telemetry_reader),
        ("battery", battery_reader),
        ("settings", settings_reader),
        ("system", system_reader),
    )

    results = {}

    for name, reader in definitions:
        section_data, error, captured = _capture_reader_call(reader)

        if error is None and not section_data and captured:
            error = "; ".join(captured)

        results[name] = {
            "data": section_data,
            "error": error,
            "warnings": (
                captured
                if error is None
                else []
            ),
        }

    return build_snapshot_from_results(
        profile_name=profile_name,
        section_results=results,
        acquisition_mode="sequential_existing_readers",
        shared_serial_session=False
    )

def read_snapshot(
        config,
        str_to_bool,
        registers_file,
        profile_name):
    """Read one full snapshot through a shared exclusive serial session.

    Public JSON schema remains deye-agent.snapshot.v1.
    """
    from .deye_reader import read_snapshot_sections_shared

    section_results = read_snapshot_sections_shared(
        config,
        str_to_bool,
        registers_file
    )

    return build_snapshot_from_results(
        profile_name=profile_name,
        section_results=section_results,
        acquisition_mode="shared_serial_session",
        shared_serial_session=True
    )

