def run_cycle(
        config,
        str_to_bool,
        registers_file,
        registers,
        mqtt_client=None,
        collect_snapshot=False,
        publish_stable_metrics=False,
        runtime_state=None,
        profile_name="single_phase_storage",
        debug=False):
    """Execute one daemon polling cycle.

    Legacy-only mode:
      read_deye_data() -> alarms -> optional legacy MQTT

    Snapshot-backed mode (stable MQTT and/or HTTP API):
      read_snapshot() once
        -> telemetry section -> alarms + optional legacy MQTT
        -> build_metrics_from_snapshot() -> optional stable MQTT
        -> runtime cache for HTTP API

    Snapshot-backed mode deliberately does not call read_deye_data()
    separately, so enabling API/metrics does not duplicate telemetry reads.
    """
    from .alarm_checker import check_alarms
    from .deye_reader import read_deye_data
    from .metrics import build_metrics_from_snapshot
    from .snapshot import read_snapshot

    collect_snapshot = bool(
        collect_snapshot
        or publish_stable_metrics
        or runtime_state is not None
    )

    snapshot = None
    metrics_document = None

    if collect_snapshot:
        snapshot = read_snapshot(
            config,
            str_to_bool,
            registers_file,
            profile_name
        )

        telemetry = snapshot.get("telemetry")
        data = telemetry if isinstance(telemetry, dict) else {}

        metrics_document = build_metrics_from_snapshot(
            snapshot
        )

        # Update the cache immediately after acquisition/normalization. MQTT
        # publication below can take additional time and must not delay the
        # data becoming visible to local HTTP readers.
        if runtime_state is not None:
            runtime_state.update_cycle(
                snapshot,
                metrics_document
            )
    else:
        data = read_deye_data(
            config,
            str_to_bool,
            registers_file
        )

        if not isinstance(data, dict):
            data = {}

    check_alarms(
        data,
        registers,
        config,
        debug=debug
    )

    legacy_publish_success = None
    metrics_publish_result = None

    if mqtt_client is not None:
        legacy_publish_success = mqtt_client.publish(
            data
        )

        if publish_stable_metrics:
            metrics_publish_result = (
                mqtt_client.publish_metrics(
                    metrics_document
                )
            )

    return {
        "telemetry": data,
        "snapshot": snapshot,
        "metrics": metrics_document,
        "legacy_publish_success": legacy_publish_success,
        "metrics_publish_result": metrics_publish_result,
    }
