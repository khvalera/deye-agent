import argparse
import errno
import json
import socket
import sys
import time

from .config import load_config, str_to_bool, CONFIG_PATH
from .deye_reader import (
    read_deye_data,
    read_raw_registers,
    read_device_info,
    read_battery_info,
    read_register_inventory,
    read_settings,
    read_system_status,
)
from .i18n import _
from .profiles import get_profile, list_profiles, resolve_registers_source
from .snapshot import read_snapshot
from .metrics import read_metrics
from .alarm_checker import check_alarms
from .registers_loader import load_registers
from .notify_email import send_email
from .notify_matrix import send_matrix_message


# Process-wide lock used by all inverter access modes.
INSTANCE_LOCK_NAME = "\0deye-agent-instance-lock"


def acquire_instance_lock(name=INSTANCE_LOCK_NAME):
    """Acquire a non-blocking process-wide lock."""
    lock_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

    try:
        lock_socket.bind(name)
    except OSError as exc:
        lock_socket.close()

        if getattr(exc, "errno", None) == errno.EADDRINUSE:
            return None

        raise RuntimeError(
            "Unable to acquire Deye Agent instance lock: {}".format(exc)
        )

    return lock_socket


def release_instance_lock(lock_socket):
    """Release a previously acquired process-wide lock."""
    if lock_socket is not None:
        lock_socket.close()


def parse_int_auto(value):
    """Parse a decimal or prefixed integer such as 182, 0xB6 or 0o266."""
    try:
        return int(value, 0)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError(
            "expected an integer such as 182 or 0xB6"
        )


def signed16(value):
    """Convert one unsigned Modbus word to a signed 16-bit integer."""
    value = int(value) & 0xFFFF
    return value - 0x10000 if value & 0x8000 else value


def build_raw_result(start, values):
    """Build a stable machine-readable representation of raw register words."""
    registers = []

    for offset, value in enumerate(values or []):
        address = start + offset
        unsigned_value = int(value) & 0xFFFF

        registers.append({
            "address": address,
            "address_hex": "0x{:04X}".format(address),
            "uint16": unsigned_value,
            "int16": signed16(unsigned_value),
            "hex": "0x{:04X}".format(unsigned_value),
        })

    return {
        "start": start,
        "count": len(registers),
        "registers": registers,
    }


def build_arg_parser():
    parser = argparse.ArgumentParser(
        description=_(
            "Deye Agent - Command line tool for retrieving data from Deye inverter"
        ),
        add_help=True
    )

    parser.add_argument(
        "--config",
        "-c",
        help=_("Path to configuration file"),
        default=CONFIG_PATH
    )

    parser.add_argument(
        "--registers",
        "-r",
        help=_("Path to the yaml file with the registers"),
        default=None
    )

    parser.add_argument(
        "--profile",
        help="Protocol profile for read/run, e.g. single_phase_storage",
        default=None
    )

    parser.add_argument(
        "--inventory-start",
        type=parse_int_auto,
        default=None,
        help="Optional first register for inventory"
    )

    parser.add_argument(
        "--inventory-end",
        type=parse_int_auto,
        default=None,
        help="Optional last register for inventory"
    )

    parser.add_argument(
        "--inventory-chunk",
        type=parse_int_auto,
        default=47,
        help="Initial inventory block size (1..125, default 47)"
    )

    parser.add_argument(
        "--inventory-deep",
        action="store_true",
        help=(
            "Split failed inventory blocks to individual registers; "
            "slower"
        )
    )

    parser.add_argument(
        "--debug",
        "-d",
        help=_("Enable DEBUG mode"),
        action="store_true"
    )

    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Output machine-readable JSON for supported commands"
    )

    parser.add_argument(
        "--start",
        type=parse_int_auto,
        help="First register for raw-read, e.g. 182 or 0xB6"
    )

    parser.add_argument(
        "--count",
        type=parse_int_auto,
        help="Number of registers for raw-read (1..125)"
    )

    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--mqtt-enable",
        dest="mqtt_enabled",
        action="store_true",
        help=_("Enable MQTT publishing (overrides config)")
    )
    group.add_argument(
        "--mqtt-disable",
        dest="mqtt_enabled",
        action="store_false",
        help=_("Disable MQTT publishing (overrides config)")
    )
    parser.set_defaults(mqtt_enabled=None)

    metrics_mqtt_group = parser.add_mutually_exclusive_group()
    metrics_mqtt_group.add_argument(
        "--mqtt-metrics-enable",
        dest="mqtt_metrics_enabled",
        action="store_true",
        help=(
            "Enable stable metrics MQTT publishing in run "
            "(overrides config)"
        )
    )
    metrics_mqtt_group.add_argument(
        "--mqtt-metrics-disable",
        dest="mqtt_metrics_enabled",
        action="store_false",
        help=(
            "Disable stable metrics MQTT publishing in run "
            "(overrides config)"
        )
    )
    parser.set_defaults(mqtt_metrics_enabled=None)

    http_api_group = parser.add_mutually_exclusive_group()
    http_api_group.add_argument(
        "--api-enable",
        dest="http_api_enabled",
        action="store_true",
        help=(
            "Enable the read-only cached HTTP API in run "
            "(overrides config)"
        )
    )
    http_api_group.add_argument(
        "--api-disable",
        dest="http_api_enabled",
        action="store_false",
        help=(
            "Disable the read-only cached HTTP API in run "
            "(overrides config)"
        )
    )
    parser.set_defaults(http_api_enabled=None)

    parser.add_argument(
        "--test-email",
        action="store_true",
        help=_("Send test notification email and exit")
    )

    parser.add_argument(
        "--test-matrix",
        action="store_true",
        help=_("Send test Matrix message and exit")
    )

    parser.add_argument(
        "command",
        nargs="?",
        default="read",
        choices=[
            "read",
            "run",
            "raw-read",
            "info",
            "battery",
            "settings",
            "system",
            "snapshot",
            "metrics",
            "publish-metrics",
            "inventory",
            "profiles",
            "auth-hash",
        ],
        help=(
            "Command: read - read configured telemetry once, "
            "run - start agent loop, raw-read - read raw Modbus registers, "
            "info - read static inverter information, "
            "battery - read lithium battery/BMS information, "
            "settings - read validated inverter settings, "
            "system - read parallel/system/meter status, "
            "snapshot - read a combined read-only API snapshot, "
            "metrics - read stable machine-friendly metrics, "
            "publish-metrics - publish stable metrics to MQTT, "
            "inventory - scan raw registers read-only, "
            "profiles - list protocol profiles, "
            "auth-hash - create a web-login password hash"
        )
    )

    return parser


def validate_arguments(parser, args):
    """Validate command-specific CLI arguments before accessing hardware."""
    if args.command == "raw-read":
        if args.start is None:
            parser.error("raw-read requires --start")
        if args.count is None:
            parser.error("raw-read requires --count")

        if args.start < 0 or args.start > 0xFFFF:
            parser.error("--start must be between 0 and 65535")

        if args.count < 1 or args.count > 125:
            parser.error("--count must be between 1 and 125")

        if args.start + args.count - 1 > 0xFFFF:
            parser.error("requested raw-read range exceeds register 65535")

    elif args.start is not None or args.count is not None:
        parser.error("--start and --count are only valid with raw-read")

    if args.profile and args.command not in (
            "read",
            "run",
            "settings",
            "system",
            "snapshot",
            "metrics",
            "publish-metrics",
            "inventory"):
        parser.error(
            "--profile is only valid with read, run, settings, system, "
            "snapshot, metrics, publish-metrics or inventory"
        )

    inventory_options_used = (
        args.inventory_start is not None
        or args.inventory_end is not None
        or args.inventory_chunk != 47
        or args.inventory_deep
    )

    if (
            inventory_options_used
            and args.command != "inventory"):
        parser.error(
            "--inventory-* options are only valid with inventory"
        )

    if args.command == "inventory":
        if (
                (args.inventory_start is None)
                != (args.inventory_end is None)):
            parser.error(
                "--inventory-start and --inventory-end "
                "must be used together"
            )

        if args.inventory_start is not None:
            if (
                    args.inventory_start < 0
                    or args.inventory_start > 0xFFFF):
                parser.error(
                    "--inventory-start must be between 0 and 65535"
                )

            if (
                    args.inventory_end < args.inventory_start
                    or args.inventory_end > 0xFFFF):
                parser.error(
                    "--inventory-end must be >= start and <= 65535"
                )

        if (
                args.inventory_chunk < 1
                or args.inventory_chunk > 125):
            parser.error(
                "--inventory-chunk must be between 1 and 125"
            )

    if (
            args.http_api_enabled is not None
            and args.command != "run"):
        parser.error(
            "--api-enable/--api-disable are only valid with run"
        )

    if args.command == "run" and args.json_output:
        parser.error(
            "--json is supported only by read, raw-read, info, battery, "
            "settings, system, snapshot, metrics and inventory"
        )

    if args.json_output and args.debug:
        parser.error("--json and --debug cannot be used together")


def main():
    parser = build_arg_parser()
    args = parser.parse_args()
    validate_arguments(parser, args)

    if args.command == "auth-hash":
        from getpass import getpass
        from .web_auth import hash_password

        password = getpass("Password: ")
        confirmation = getpass("Confirm password: ")

        if not password:
            parser.error("password must not be empty")

        if password != confirmation:
            parser.error("passwords do not match")

        print(hash_password(password))
        return

    if args.command == "profiles":
        profiles = list_profiles()

        if args.json_output:
            print(
                json.dumps(
                    profiles,
                    ensure_ascii=False,
                    sort_keys=False
                )
            )
        else:
            print("Deye protocol profiles:")
            for profile in profiles:
                print(
                    "  {:24} supported={:<5} status={:<18} {}".format(
                        profile["name"],
                        str(profile["supported"]).lower(),
                        profile["status"],
                        profile["family"]
                    )
                )
        return

    config = load_config(args.config)

    if args.debug:
        config["DEBUG"] = "true"

    # JSON mode must keep stdout machine-readable even if DEBUG=true in config.
    if args.json_output:
        config["DEBUG"] = "false"

    if args.mqtt_enabled is not None:
        config["MQTT_ENABLED"] = "true" if args.mqtt_enabled else "false"

    if args.mqtt_metrics_enabled is not None:
        config["MQTT_METRICS_ENABLED"] = (
            "true"
            if args.mqtt_metrics_enabled
            else "false"
        )

    if args.http_api_enabled is not None:
        config["HTTP_API_ENABLED"] = (
            "true"
            if args.http_api_enabled
            else "false"
        )

    debug = str_to_bool(config.get("DEBUG", "false"))

    if debug:
        print(_("Starting Deye Agent..."))
        print(_("Loaded configuration from {}").format(args.config))

    registers_file = None
    active_profile = None
    registers_source = None

    if args.command in (
            "read",
            "run",
            "snapshot",
            "metrics",
            "publish-metrics"):
        registers_file, active_profile, registers_source = (
            resolve_registers_source(
                config,
                cli_registers=args.registers,
                cli_profile=args.profile
            )
        )

        if debug:
            if active_profile:
                print(
                    "Using protocol profile {} ({})".format(
                        active_profile,
                        registers_source
                    )
                )
            print(_("Using registers from {}").format(registers_file))

    # Notification-only modes do not need register definitions or inverter lock.
    if args.test_email:
        try:
            send_email(
                config,
                subject="📧️Deye Agent Test Email",
                body="📩 This is a test notification from Deye Agent.",
                debug=True
            )
        except Exception as e:
            print(_("Error sending test email:"), e)
        print(_("Test email sent. Exiting."))
        return

    if args.test_matrix:
        try:
            send_matrix_message(
                config,
                message="🔔 This is a test Matrix notification from Deye Agent.",
                debug=True
            )
        except Exception as e:
            print(_("Error sending test Matrix message:"), e)
        print(_("Test Matrix message sent. Exiting."))
        return

    # Only read/run need alarm metadata from registers.yaml.
    registers = None
    if args.command in ("read", "run"):
        registers = load_registers(registers_file)

    update_interval = int(config.get("UPDATE_INTERVAL", "60"))

    try:
        instance_lock = acquire_instance_lock()
    except Exception as e:
        print(_("Error:"), e, file=sys.stderr)
        sys.exit(1)

    if instance_lock is None:
        print(
            _("Another Deye Agent instance is already running."),
            file=sys.stderr
        )
        sys.exit(1)

    try:
        # -------------------------------------------------------------
        # FULL READ-ONLY REGISTER INVENTORY MODE
        # -------------------------------------------------------------
        if args.command == "inventory":
            profile_name = (
                args.profile
                or str(
                    config.get(
                        "PROFILE",
                        ""
                    )
                ).strip()
                or "single_phase_storage"
            )

            profile = get_profile(
                profile_name
            )

            inventory_ranges = profile.get(
                "inventory_ranges",
                []
            )

            if not profile.get(
                    "supported",
                    False):
                raise RuntimeError(
                    "protocol profile '{}' is not enabled for runtime "
                    "inventory".format(
                        profile_name
                    )
                )

            if (
                    args.inventory_start is not None
                    and args.inventory_end is not None):
                inventory_ranges = [[
                    args.inventory_start,
                    args.inventory_end
                ]]

            if not inventory_ranges:
                raise RuntimeError(
                    "no inventory ranges configured for protocol profile "
                    "'{}'".format(
                        profile_name
                    )
                )

            min_chunk_size = (
                1
                if args.inventory_deep
                else 8
            )

            def inventory_progress(event):
                if event["status"] == "readable":
                    action = "OK"
                elif event["status"] == "split":
                    action = "FAIL -> split"
                else:
                    action = "FAIL terminal"

                percent = (
                    100.0
                    * event["completed"]
                    / event["total"]
                    if event["total"]
                    else 100.0
                )

                print(
                    "[inventory] {:5d}-{:5d} {:13} "
                    "completed={:5d}/{:5d} "
                    "({:5.1f}%) probes={}".format(
                        event["start"],
                        event["end"],
                        action,
                        event["completed"],
                        event["total"],
                        percent,
                        event["probes"]
                    ),
                    file=sys.stderr,
                    flush=True
                )

            print(
                "[inventory] profile={} ranges={} mode={} "
                "chunk={} attempts={}".format(
                    profile_name,
                    ",".join(
                        "{}-{}".format(
                            item[0],
                            item[1]
                        )
                        for item in inventory_ranges
                    ),
                    (
                        "deep"
                        if args.inventory_deep
                        else "fast"
                    ),
                    args.inventory_chunk,
                    config.get(
                        "INVENTORY_READ_ATTEMPTS",
                        "1"
                    )
                ),
                file=sys.stderr,
                flush=True
            )

            result = read_register_inventory(
                config,
                str_to_bool,
                inventory_ranges,
                chunk_size=args.inventory_chunk,
                min_chunk_size=min_chunk_size,
                profile_name=profile_name,
                progress_callback=inventory_progress
            )

            if args.json_output:
                print(
                    json.dumps(
                        result,
                        ensure_ascii=False,
                        sort_keys=False
                    )
                )
            else:
                summary = result["summary"]

                print(
                    "Deye read-only register inventory:"
                )

                print(
                    "  profile                     : {}".format(
                        profile_name
                    )
                )

                print(
                    "  function code               : 0x03 (read only)"
                )

                print(
                    "  scan mode                   : {}".format(
                        result["scan_mode"]
                    )
                )

                print(
                    "  ranges                      : {}".format(
                        ", ".join(
                            "{}-{}".format(
                                item["start"],
                                item["end"]
                            )
                            for item in result["ranges"]
                        )
                    )
                )

                print(
                    "  initial chunk               : {}".format(
                        result["chunk_size"]
                    )
                )

                print(
                    "  probes                      : {}".format(
                        result["probes"]
                    )
                )

                print(
                    "  requested registers         : {}".format(
                        summary["requested"]
                    )
                )

                print(
                    "  readable                    : {}".format(
                        summary["readable"]
                    )
                )

                print(
                    "  single no-response          : {}".format(
                        summary[
                            "no_response_after_retries"
                        ]
                    )
                )

                print(
                    "  block no-response           : {}".format(
                        summary[
                            "block_no_response_after_retries"
                        ]
                    )
                )

                print(
                    "  zero-valued readable        : {}".format(
                        summary["zero"]
                    )
                )

                print(
                    "  nonzero readable            : {}".format(
                        summary["nonzero"]
                    )
                )

                print("")
                print(
                    "Non-zero readable registers:"
                )

                for item in result["registers"]:
                    if (
                            item["status"] == "readable"
                            and not item["zero"]):
                        print(
                            "  {:5d}  {:>6}  "
                            "uint16={:5d}  "
                            "int16={:6d}  {}".format(
                                item["address"],
                                item["address_hex"],
                                item["uint16"],
                                item["int16"],
                                item["hex"]
                            )
                        )

            return

        # -------------------------------------------------------------
        # EXPLICIT MQTT PUBLICATION OF STABLE METRICS
        # -------------------------------------------------------------
        if args.command == "publish-metrics":
            profile_name = (
                args.profile
                or str(config.get("PROFILE", "")).strip()
                or active_profile
                or "single_phase_storage"
            )

            profile = get_profile(profile_name)

            if not profile.get("supported", False):
                raise RuntimeError(
                    "protocol profile '{}' is not enabled for runtime "
                    "metrics".format(profile_name)
                )

            if not profile.get("metrics_supported", False):
                raise RuntimeError(
                    "metrics are not available for protocol profile "
                    "'{}'".format(profile_name)
                )

            metrics_result = read_metrics(
                config,
                str_to_bool,
                registers_file,
                profile_name
            )

            from .mqtt_client import MQTTClient

            mqtt = MQTTClient(
                config,
                debug=debug
            )

            if not mqtt.connect():
                raise RuntimeError(
                    "failed to connect to MQTT broker"
                )

            try:
                publish_result = mqtt.publish_metrics(
                    metrics_result
                )
            finally:
                mqtt.disconnect()

            if args.json_output:
                print(
                    json.dumps(
                        publish_result,
                        ensure_ascii=False,
                        sort_keys=False
                    )
                )
            else:
                print("Deye MQTT metrics publication:")
                print(
                    "  Topic root                 : {}".format(
                        publish_result["topic_root"]
                    )
                )
                print(
                    "  Published / total          : {} / {}".format(
                        publish_result["metrics_published"],
                        publish_result["metrics_total"]
                    )
                )
                print(
                    "  Failed                     : {}".format(
                        publish_result["metrics_failed"]
                    )
                )

            if not publish_result["complete"]:
                raise RuntimeError(
                    "MQTT metrics publication incomplete: "
                    "{} metric(s) failed".format(
                        publish_result["metrics_failed"]
                    )
                )

            return

        # -------------------------------------------------------------
        # STABLE MACHINE-FRIENDLY METRICS MODE
        # -------------------------------------------------------------
        if args.command == "metrics":
            profile_name = (
                args.profile
                or str(config.get("PROFILE", "")).strip()
                or active_profile
                or "single_phase_storage"
            )

            profile = get_profile(profile_name)

            if not profile.get("supported", False):
                raise RuntimeError(
                    "protocol profile '{}' is not enabled for runtime "
                    "metrics".format(profile_name)
                )

            if not profile.get("metrics_supported", False):
                raise RuntimeError(
                    "metrics are not available for protocol profile "
                    "'{}'".format(profile_name)
                )

            result = read_metrics(
                config,
                str_to_bool,
                registers_file,
                profile_name
            )

            if args.json_output:
                print(
                    json.dumps(
                        result,
                        ensure_ascii=False,
                        sort_keys=False
                    )
                )
            else:
                summary = result["summary"]

                print("Deye normalized metrics:")
                print(
                    "  Schema                    : {}".format(
                        result["schema"]
                    )
                )
                print(
                    "  Profile                   : {}".format(
                        result["profile"]
                    )
                )
                print(
                    "  Status                    : {}".format(
                        summary["status"]
                    )
                )
                print(
                    "  Available / total         : {} / {}".format(
                        summary["metrics_available"],
                        summary["metrics_total"]
                    )
                )
                print("")

                for metric_id in sorted(result["metrics"]):
                    metric = result["metrics"][metric_id]

                    if not metric["available"]:
                        rendered = "unavailable"
                    else:
                        value = metric["value"]

                        if isinstance(value, bool):
                            rendered = (
                                "true"
                                if value
                                else "false"
                            )
                        else:
                            rendered = str(value)

                        if metric["unit"]:
                            rendered += " {}".format(
                                metric["unit"]
                            )

                    print(
                        "  {:46} {}".format(
                            metric_id,
                            rendered
                        )
                    )

            return

        # -------------------------------------------------------------
        # COMBINED READ-ONLY SNAPSHOT MODE
        # -------------------------------------------------------------
        if args.command == "snapshot":
            profile_name = (
                args.profile
                or str(config.get("PROFILE", "")).strip()
                or active_profile
                or "single_phase_storage"
            )

            profile = get_profile(profile_name)

            if not profile.get("supported", False):
                raise RuntimeError(
                    "protocol profile '{}' is not enabled for runtime "
                    "snapshot".format(profile_name)
                )

            if not profile.get("snapshot_supported", False):
                raise RuntimeError(
                    "snapshot is not available for protocol profile "
                    "'{}'".format(profile_name)
                )

            snapshot = read_snapshot(
                config,
                str_to_bool,
                registers_file,
                profile_name
            )

            if args.json_output:
                print(
                    json.dumps(
                        snapshot,
                        ensure_ascii=False,
                        sort_keys=False
                    )
                )
            else:
                summary = snapshot["summary"]

                print("Deye read-only snapshot:")
                print(
                    "  Schema                      : {}".format(
                        snapshot["schema"]
                    )
                )
                print(
                    "  Profile                     : {}".format(
                        snapshot["profile"]
                    )
                )
                print(
                    "  Status                      : {}".format(
                        summary["status"]
                    )
                )
                print(
                    "  Sections ok/partial/error   : {} / {} / {}".format(
                        summary["sections_ok"],
                        summary["sections_partial"],
                        summary["sections_error"]
                    )
                )

                info = snapshot.get("device_info")
                if info:
                    print("")
                    print("  Device:")
                    print(
                        "    Serial                    : {}".format(
                            info.get("serial_number")
                        )
                    )
                    print(
                        "    Type                      : {}".format(
                            info.get("device_type")
                        )
                    )
                    print(
                        "    Rated power               : {} W".format(
                            info.get("rated_power_w")
                        )
                    )

                telemetry = snapshot.get("telemetry")
                if telemetry:
                    print("")
                    print("  Telemetry:")
                    for name in (
                            "Grid Voltage",
                            "Grid Power",
                            "Inverter Output Power",
                            "Load Power",
                            "Battery Voltage",
                            "Battery Capacity",
                            "Battery Power",
                            "PV1 Power",
                            "PV2 Power"):
                        if name in telemetry:
                            print(
                                "    {:25}: {}".format(
                                    name,
                                    telemetry[name]
                                )
                            )

                print("")
                print("  Section status:")
                for name, status in snapshot["section_status"].items():
                    line = "    {:12}: {}".format(
                        name,
                        status["status"]
                    )

                    if status.get("error"):
                        line += " ({})".format(status["error"])
                    elif status.get("partial_reason"):
                        line += " ({})".format(
                            status["partial_reason"]
                        )

                    print(line)

            return

        # -------------------------------------------------------------
        # READ-ONLY SYSTEM / PARALLEL / METER STATUS MODE
        # -------------------------------------------------------------
        if args.command == "system":
            profile_name = (
                args.profile
                or str(config.get("PROFILE", "")).strip()
                or "single_phase_storage"
            )

            profile = get_profile(profile_name)

            if not profile.get("supported", False):
                raise RuntimeError(
                    "protocol profile '{}' is not enabled for runtime "
                    "system status".format(profile_name)
                )

            if not profile.get("system_status_supported", False):
                raise RuntimeError(
                    "system status decoder is not available for "
                    "protocol profile '{}'".format(profile_name)
                )

            system_status = read_system_status(
                config,
                str_to_bool
            )

            if system_status is None:
                raise RuntimeError(
                    "system status read failed after configured retries"
                )

            if args.json_output:
                print(
                    json.dumps(
                        system_status,
                        ensure_ascii=False,
                        sort_keys=False
                    )
                )
            else:
                print("Deye read-only system status:")

                parallel = system_status["parallel"]
                print("")
                print("  Parallel:")
                print(
                    "    Enabled                     : {}".format(
                        "yes"
                        if parallel["parallel_enabled"]
                        else "no"
                    )
                )
                print(
                    "    Modbus SN                   : {}".format(
                        parallel["modbus_sn"]
                    )
                )
                print(
                    "    Register 1 raw              : {}".format(
                        parallel["register_1_raw_hex"]
                    )
                )
                print(
                    "    A/B/C inverter count        : {} / {} / {}".format(
                        parallel["a_phase_inverter_count"],
                        parallel["b_phase_inverter_count"],
                        parallel["c_phase_inverter_count"]
                    )
                )

                version = system_status["lithium_battery_version"]
                print("")
                print("  Lithium battery version:")
                print(
                    "    Low / high                  : {} / {}".format(
                        version["low_word_hex"],
                        version["high_word_hex"]
                    )
                )
                print(
                    "    uint32                      : {}".format(
                        version["uint32_low_word_first"]
                    )
                )

                print("")
                print("  System time:")
                time_raw = system_status["system_time_raw"]
                print(
                    "    Decoded                     : unavailable"
                )
                print(
                    "    Raw words                   : {}".format(
                        " ".join(
                            item["raw_hex"]
                            for item in time_raw["registers"]
                        )
                    )
                )

                meter = system_status["meter_active_power"]["values"]
                print("")
                print("  Meter active power:")
                print(
                    "    Total                       : {} W".format(
                        meter["total"]["signed_int32_w"]
                    )
                )
                print(
                    "    Phase A / B / C             : {} / {} / {} W".format(
                        meter["phase_a"]["signed_int32_w"],
                        meter["phase_b"]["signed_int32_w"],
                        meter["phase_c"]["signed_int32_w"]
                    )
                )

                energy = system_status["meter_energy_raw_432_437"]
                print("")
                print("  Meter energy 432-437:")
                print("    Semantic decoding           : disabled")
                for item in energy["registers"]:
                    print(
                        "    {:>3}                         : {}".format(
                            item["address"],
                            item["raw_hex"]
                        )
                    )

                revision = system_status[
                    "revision_sensitive_raw_438_499"
                ]

                print("")
                print("  Revision-sensitive 438-499:")
                print("    Semantic decoding           : disabled")
                print(
                    "    Zero / non-zero             : {} / {}".format(
                        revision["zero_count"],
                        revision["nonzero_count"]
                    )
                )
                print("    Non-zero registers:")

                for item in revision["registers"]:
                    if item["zero"]:
                        continue

                    print(
                        "      {:>3}  {}  uint16={:5d}  int16={:6d}".format(
                            item["address"],
                            item["raw_hex"],
                            item["raw"],
                            item["int16"]
                        )
                    )

            return

        # -------------------------------------------------------------
        # READ-ONLY VALIDATED SETTINGS MODE
        # -------------------------------------------------------------
        if args.command == "settings":
            profile_name = (
                args.profile
                or str(config.get("PROFILE", "")).strip()
                or "single_phase_storage"
            )

            profile = get_profile(profile_name)

            if not profile.get("supported", False):
                raise RuntimeError(
                    "protocol profile '{}' is not enabled for runtime "
                    "settings".format(profile_name)
                )

            if not profile.get("settings_supported", False):
                raise RuntimeError(
                    "read-only settings decoder is not available for "
                    "protocol profile '{}'".format(profile_name)
                )

            settings = read_settings(
                config,
                str_to_bool
            )

            if settings is None:
                raise RuntimeError(
                    "settings read failed after configured retries"
                )

            if args.json_output:
                print(
                    json.dumps(
                        settings,
                        ensure_ascii=False,
                        sort_keys=False
                    )
                )
            else:
                print("Deye read-only inverter settings:")

                battery_config = settings.get("battery_configuration")
                if battery_config is not None:
                    print("")
                    print("  Battery configuration:")
                    print(
                        "    Control mode                : {}".format(
                            battery_config["control_mode"]["mode"]
                            or "Unknown"
                        )
                    )
                    print(
                        "    Equalization / absorption   : {:.2f} / {:.2f} V".format(
                            battery_config["equalization_voltage_v"],
                            battery_config["absorption_voltage_v"]
                        )
                    )
                    print(
                        "    Float / empty voltage       : {:.2f} / {:.2f} V".format(
                            battery_config["float_voltage_v"],
                            battery_config["empty_voltage_v"]
                        )
                    )
                    print(
                        "    Battery capacity            : {} Ah".format(
                            battery_config["capacity_ah"]
                        )
                    )
                    print(
                        "    Max charge / discharge      : {} / {} A".format(
                            battery_config["max_charge_current_a"],
                            battery_config["max_discharge_current_a"]
                        )
                    )
                    print(
                        "    Operating basis             : {}".format(
                            battery_config["operating_basis"]["mode"]
                            or "Unknown"
                        )
                    )
                    wake_enabled = battery_config[
                        "lithium_battery_wake"
                    ]["enabled"]
                    print(
                        "    Lithium battery wake        : {}".format(
                            "Enabled"
                            if wake_enabled is True
                            else "Disabled"
                            if wake_enabled is False
                            else "Unknown"
                        )
                    )
                    print(
                        "    Charge efficiency           : {:.1f} %".format(
                            battery_config["charging_efficiency_percent"]
                        )
                    )
                    soc = battery_config["soc_thresholds_percent"]
                    voltage = battery_config["voltage_thresholds_v"]
                    print(
                        "    SOC shutdown/restart/low    : {} / {} / {} %".format(
                            soc["shutdown"],
                            soc["restart"],
                            soc["low_battery"]
                        )
                    )
                    print(
                        "    V shutdown/restart/low      : {:.2f} / {:.2f} / {:.2f} V".format(
                            voltage["shutdown"],
                            voltage["restart"],
                            voltage["low_battery"]
                        )
                    )

                generator = settings.get("generator_and_charging")
                if generator is not None:
                    print("")
                    print("  Generator / charging:")
                    print(
                        "    Max run / cooling           : {:.1f} / {:.1f} h".format(
                            generator["maximum_generator_run_time_hours"],
                            generator["generator_cooling_time_hours"]
                        )
                    )
                    gen_charge = generator["generator_charge"]
                    grid_charge = generator["grid_charge"]
                    print(
                        "    GEN start V / SOC / current : {:.2f} V / {} % / {} A".format(
                            gen_charge["start_voltage_v"],
                            gen_charge["start_soc_percent"],
                            gen_charge["current_a"]
                        )
                    )
                    print(
                        "    GRID start V / SOC / current: {:.2f} V / {} % / {} A".format(
                            grid_charge["start_voltage_v"],
                            grid_charge["start_soc_percent"],
                            grid_charge["current_a"]
                        )
                    )
                    print(
                        "    GEN/GRID enable raw         : {} / {}".format(
                            gen_charge["enable_raw_hex"],
                            grid_charge["enable_raw_hex"]
                        )
                    )

                generator_port = settings.get("generator_port_and_smart_load")
                if generator_port is not None:
                    print("")
                    print("  Generator port / SmartLoad:")
                    print(
                        "    Solar input                 : {}".format(
                            generator_port["solar_input"]["mode"]
                            or "Unknown"
                        )
                    )
                    print(
                        "    Generator port mode         : {}".format(
                            generator_port["generator_port_mode"]["mode"]
                            or "Unknown"
                        )
                    )
                    smart_load = generator_port["smart_load"]
                    print(
                        "    SmartLoad OFF V / SOC       : {:.2f} V / {} %".format(
                            smart_load["off_battery_voltage_v"],
                            smart_load["off_battery_soc_percent"]
                        )
                    )
                    print(
                        "    SmartLoad ON V / SOC        : {:.2f} V / {} %".format(
                            smart_load["on_battery_voltage_v"],
                            smart_load["on_battery_soc_percent"]
                        )
                    )
                    print(
                        "    Energy management           : {}".format(
                            generator_port["energy_management"]["mode"]
                            or "Unknown"
                        )
                    )
                    print(
                        "    Limit control               : {}".format(
                            generator_port["limit_control"]["mode"]
                            or "Unknown"
                        )
                    )
                    print(
                        "    Gen_Grid_Signal raw         : {}".format(
                            generator_port["gen_grid_signal_on_raw_hex"]
                        )
                    )

                grid_support = settings.get(
                    "grid_support_configuration"
                )

                if grid_support is not None:
                    print("")
                    print("  Extended grid support:")

                    if not grid_support.get("available", False):
                        print(
                            "    Extended settings          : unavailable"
                        )
                    else:
                        lhvrt = grid_support[
                            "california_voltage_ride_through"
                        ]
                        lhf_rt = grid_support[
                            "california_frequency_ride_through"
                        ]

                        lhvrt_enabled = lhvrt["enable"]["enabled"]
                        lhf_rt_enabled = lhf_rt["enable"]["enabled"]

                        print(
                            "    CA LHVRT                    : {}".format(
                                "Enabled"
                                if lhvrt_enabled is True
                                else "Disabled"
                                if lhvrt_enabled is False
                                else "Unknown"
                            )
                        )

                        print(
                            "    CA LHVRT H2/H1/L1/L2/L3    : "
                            "{:.1f} / {:.1f} / {:.1f} / {:.1f} / {:.1f} V".format(
                                lhvrt["voltage_v"]["high_2"],
                                lhvrt["voltage_v"]["high_1"],
                                lhvrt["voltage_v"]["low_1"],
                                lhvrt["voltage_v"]["low_2"],
                                lhvrt["voltage_v"]["low_3"]
                            )
                        )

                        print(
                            "    CA LHFRT                    : {}".format(
                                "Enabled"
                                if lhf_rt_enabled is True
                                else "Disabled"
                                if lhf_rt_enabled is False
                                else "Unknown"
                            )
                        )

                        print(
                            "    CA LHFRT H2/H1/L1/L2        : "
                            "{:.2f} / {:.2f} / {:.2f} / {:.2f} Hz".format(
                                lhf_rt["frequency_hz"]["high_2"],
                                lhf_rt["frequency_hz"]["high_1"],
                                lhf_rt["frequency_hz"]["low_1"],
                                lhf_rt["frequency_hz"]["low_2"]
                            )
                        )

                        print(
                            "    CA validation               : {} / {}".format(
                                lhvrt["validation"]["status"],
                                lhf_rt["validation"]["status"]
                            )
                        )

                        tail = grid_support["raw_unvalidated_351_416"]
                        print(
                            "    Raw-only 351-416            : "
                            "{} nonzero / {} zero".format(
                                tail["nonzero_count"],
                                tail["zero_count"]
                            )
                        )

                print("")
                print(
                    "  Maximum grid power           : {} W".format(
                        settings["maximum_grid_power_w"]
                    )
                )

                solar = settings["solar_sell"]["enabled"]
                print(
                    "  Solar sell                   : {}".format(
                        "Enabled"
                        if solar is True
                        else "Disabled"
                        if solar is False
                        else "Unknown"
                    )
                )

                tou = settings["time_of_use"]

                print(
                    "  Time of Use                  : {}".format(
                        "Enabled" if tou["enabled"] else "Disabled"
                    )
                )
                print(
                    "  TOU enabled days             : {}".format(
                        ", ".join(tou["enabled_days"])
                        if tou["enabled_days"]
                        else "none"
                    )
                )
                print(
                    "  TOU work mode 3              : {}".format(
                        "On" if tou["work_mode_3"] else "Off"
                    )
                )

                print("")
                print("  TOU slots:")

                for slot in tou["slots"]:
                    print(
                        "    {}: {}  power={} W  voltage={:.2f} V  "
                        "SOC={} %  grid_charge={}  gen_charge={}  "
                        "GM={}  BU={}  CH={}".format(
                            slot["slot"],
                            slot["time"] or "invalid",
                            slot["power_w"],
                            slot["battery_voltage_v"],
                            slot["soc_percent"],
                            "on" if slot["grid_charge_enabled"] else "off",
                            (
                                "on"
                                if slot["generator_charge_enabled"]
                                else "off"
                            ),
                            "on" if slot["gm_mode"] else "off",
                            "on" if slot["bu_mode"] else "off",
                            "on" if slot["ch_mode"] else "off",
                        )
                    )

                grid = settings["grid"]

                print("")
                print("  Grid / protection:")
                print(
                    "    Restore connection         : {} s".format(
                        grid["restore_connection_time_s"]
                    )
                )
                print(
                    "    Solar Arc Fault mode       : {}".format(
                        grid["solar_arc_fault_mode"]
                    )
                )
                print(
                    "    Grid mode                  : {}".format(
                        grid["grid_mode"]
                    )
                )
                print(
                    "    Grid frequency             : {} Hz".format(
                        grid["grid_frequency_hz"]
                    )
                )
                print(
                    "    Grid type                  : {}".format(
                        grid["grid_type"]
                    )
                )
                print(
                    "    Voltage high / low         : {:.1f} / {:.1f} V".format(
                        grid["voltage_high_v"],
                        grid["voltage_low_v"]
                    )
                )
                print(
                    "    Frequency high / low       : {:.2f} / {:.2f} Hz".format(
                        grid["frequency_high_hz"],
                        grid["frequency_low_hz"]
                    )
                )

                gen_input = grid["generator_connected_to_grid_input"]
                print(
                    "    Generator on grid input    : {}".format(
                        "Enabled"
                        if gen_input is True
                        else "Disabled"
                        if gen_input is False
                        else "Unknown"
                    )
                )

                print(
                    "    GEN peak shaving power     : {} W".format(
                        grid["generator_peak_shaving_power_w"]
                    )
                )
                print(
                    "    GRID peak shaving power    : {} W".format(
                        grid["grid_peak_shaving_power_w"]
                    )
                )
                print(
                    "    SmartLoad open delay       : {} min".format(
                        grid["smart_load_open_delay_min"]
                    )
                )
                print(
                    "    Output PF setting          : {:.1f} %".format(
                        grid["output_pf_setting_percent"]
                    )
                )
                print(
                    "    External relay raw         : {}".format(
                        grid["external_relay_raw_hex"]
                    )
                )

                print("")
                print("  Undecoded raw:")

                for address in sorted(
                        settings["undecoded_raw"],
                        key=lambda value: int(value)):
                    item = settings["undecoded_raw"][address]
                    print(
                        "    {:>3}                       : {}".format(
                            address,
                            item["raw_hex"]
                        )
                    )

            return

        # -------------------------------------------------------------
        # BATTERY / BMS INFO MODE
        # -------------------------------------------------------------
        if args.command == "battery":
            battery = read_battery_info(
                config,
                str_to_bool
            )

            if battery is None:
                raise RuntimeError(
                    "battery info read failed after configured retries"
                )

            if args.json_output:
                print(
                    json.dumps(
                        battery,
                        ensure_ascii=False,
                        sort_keys=False
                    )
                )
            else:
                print("Deye battery/BMS information:")
                for key, value in battery.items():
                    print("  {:36}: {}".format(key, value))

            return

        # -------------------------------------------------------------
        # DEVICE INFO MODE
        # -------------------------------------------------------------
        if args.command == "info":
            info = read_device_info(
                config,
                str_to_bool
            )

            if info is None:
                raise RuntimeError(
                    "device info read failed after configured retries"
                )

            if args.json_output:
                print(
                    json.dumps(
                        info,
                        ensure_ascii=False,
                        sort_keys=False
                    )
                )
            else:
                print("Deye inverter information:")
                for key, value in info.items():
                    print("  {:34}: {}".format(key, value))

            return

        # -------------------------------------------------------------
        # RAW READ MODE
        # -------------------------------------------------------------
        if args.command == "raw-read":
            values = read_raw_registers(
                config,
                str_to_bool,
                args.start,
                args.count
            )

            if values is None:
                raise RuntimeError(
                    "raw-read failed after configured retries"
                )

            result = build_raw_result(args.start, values)

            if args.json_output:
                print(
                    json.dumps(
                        result,
                        ensure_ascii=False,
                        sort_keys=False
                    )
                )
            else:
                print(
                    "Raw registers {}-{}:".format(
                        args.start,
                        args.start + len(values) - 1
                    )
                )
                print(
                    "  {:>7}  {:>8}  {:>8}  {:>8}  {:>8}".format(
                        "Address",
                        "AddrHex",
                        "UInt16",
                        "Int16",
                        "ValueHex"
                    )
                )

                for item in result["registers"]:
                    print(
                        "  {:7d}  {:>8}  {:8d}  {:8d}  {:>8}".format(
                            item["address"],
                            item["address_hex"],
                            item["uint16"],
                            item["int16"],
                            item["hex"]
                        )
                    )

            return

        # -------------------------------------------------------------
        # READ MODE
        # -------------------------------------------------------------
        if args.command == "read":
            data = read_deye_data(config, str_to_bool, registers_file)

            if args.json_output:
                # JSON mode is intentionally side-effect free. This keeps stdout
                # suitable for APIs/scripts and avoids notification/MQTT output.
                print(
                    json.dumps(
                        data,
                        ensure_ascii=False,
                        sort_keys=False
                    )
                )
                return

            print(_("Inverter data:"))
            for key, value in data.items():
                print("  {:30}: {}".format(_(key), value))

            check_alarms(data, registers, config, debug=debug)

            if config.get("MQTT_ENABLED", "false").lower() == "true":
                from .mqtt_client import MQTTClient
                mqtt = MQTTClient(config, debug=debug)
                if mqtt.connect():
                    mqtt.publish(data)
                    mqtt.disconnect()

        # -------------------------------------------------------------
        # RUN MODE
        # -------------------------------------------------------------
        elif args.command == "run":
            from .mqtt_client import MQTTClient
            from .runtime import run_cycle
            from .runtime_state import RuntimeState
            from .http_api import start_http_api

            mqtt = None
            http_api = None
            runtime_state = None

            mqtt_enabled = str_to_bool(
                config.get("MQTT_ENABLED", "false")
            )
            mqtt_metrics_enabled = str_to_bool(
                config.get(
                    "MQTT_METRICS_ENABLED",
                    "false"
                )
            )
            http_api_enabled = str_to_bool(
                config.get(
                    "HTTP_API_ENABLED",
                    "false"
                )
            )
            # MQTT_ENABLED remains the existing master switch.
            publish_stable_metrics = (
                mqtt_enabled
                and mqtt_metrics_enabled
            )

            # Both stable MQTT and the HTTP API consume the same snapshot.
            # This never results in a second telemetry acquisition.
            collect_snapshot = (
                publish_stable_metrics
                or http_api_enabled
            )

            profile_name = (
                args.profile
                or str(config.get("PROFILE", "")).strip()
                or active_profile
                or "single_phase_storage"
            )

            if collect_snapshot:
                profile = get_profile(profile_name)

                if not profile.get("supported", False):
                    raise RuntimeError(
                        "protocol profile '{}' is not enabled for runtime "
                        "snapshot/metrics".format(profile_name)
                    )

                if not profile.get("snapshot_supported", False):
                    raise RuntimeError(
                        "snapshot is not available for protocol profile "
                        "'{}'".format(profile_name)
                    )

                if not profile.get("metrics_supported", False):
                    raise RuntimeError(
                        "metrics are not available for protocol profile "
                        "'{}'".format(profile_name)
                    )

            if debug:
                print(
                    "MQTT legacy topics: {}".format(
                        "enabled"
                        if mqtt_enabled
                        else "disabled"
                    )
                )
                print(
                    "MQTT stable metrics: {}".format(
                        "enabled"
                        if publish_stable_metrics
                        else "disabled"
                    )
                )
                print(
                    "HTTP API: {}".format(
                        "enabled"
                        if http_api_enabled
                        else "disabled"
                    )
                )
                print(
                    "HTTP authentication: {}".format(
                        "required"
                        if http_api_enabled
                        else "inactive"
                    )
                )

                if (
                        mqtt_metrics_enabled
                        and not mqtt_enabled):
                    print(
                        "MQTT stable metrics requested but inactive because "
                        "MQTT_ENABLED is false"
                    )

            if mqtt_enabled:
                mqtt = MQTTClient(config, debug=debug)

                if not mqtt.connect():
                    print(
                        _(
                            "Failed to connect to MQTT broker, exiting."
                        )
                    )
                    sys.exit(1)

            if http_api_enabled:
                api_host = str(
                    config.get(
                        "HTTP_API_HOST",
                        "127.0.0.1"
                    )
                ).strip() or "127.0.0.1"

                try:
                    api_port = int(
                        config.get(
                            "HTTP_API_PORT",
                            "8765"
                        )
                    )
                except (TypeError, ValueError):
                    raise RuntimeError(
                        "HTTP_API_PORT must be an integer"
                    )

                if api_port < 1 or api_port > 65535:
                    raise RuntimeError(
                        "HTTP_API_PORT must be between 1 and 65535"
                    )

                history_enabled = str_to_bool(
                    config.get(
                        "HTTP_HISTORY_ENABLED",
                        "true"
                    )
                )

                try:
                    history_max_samples = int(
                        config.get(
                            "HTTP_HISTORY_MAX_SAMPLES",
                            "720"
                        )
                    )
                    history_retention_seconds = int(
                        config.get(
                            "HTTP_HISTORY_RETENTION_SECONDS",
                            "21600"
                        )
                    )
                except (TypeError, ValueError):
                    raise RuntimeError(
                        "HTTP history limits must be integers"
                    )

                if history_max_samples < 2:
                    raise RuntimeError(
                        "HTTP_HISTORY_MAX_SAMPLES must be at least 2"
                    )

                if history_retention_seconds < 60:
                    raise RuntimeError(
                        "HTTP_HISTORY_RETENTION_SECONDS must be at least 60"
                    )

                # HTTP API is always authenticated. Missing credentials
                # are a configuration error; never expose an unprotected UI.
                auth_username = str(
                    config.get(
                        "HTTP_AUTH_USERNAME",
                        ""
                    )
                ).strip()
                auth_password_hash = str(
                    config.get(
                        "HTTP_AUTH_PASSWORD_HASH",
                        ""
                    )
                ).strip()

                try:
                    auth_session_seconds = int(
                        config.get(
                            "HTTP_AUTH_SESSION_SECONDS",
                            "43200"
                        )
                    )
                except (TypeError, ValueError):
                    raise RuntimeError(
                        "HTTP_AUTH_SESSION_SECONDS must be an integer"
                    )

                auth_cookie_secure = str_to_bool(
                    config.get(
                        "HTTP_AUTH_COOKIE_SECURE",
                        "false"
                    )
                )

                if not auth_username:
                    raise RuntimeError(
                        "HTTP_API_ENABLED=true requires "
                        "HTTP_AUTH_USERNAME"
                    )

                if not auth_password_hash:
                    raise RuntimeError(
                        "HTTP_API_ENABLED=true requires "
                        "HTTP_AUTH_PASSWORD_HASH"
                    )

                runtime_state = RuntimeState(
                    profile_name=profile_name,
                    mqtt_enabled=mqtt_enabled,
                    mqtt_metrics_enabled=(
                        publish_stable_metrics
                    ),
                    http_api_enabled=True,
                    history_enabled=history_enabled,
                    history_max_samples=history_max_samples,
                    history_retention_seconds=(
                        history_retention_seconds
                    )
                )

                http_api = start_http_api(
                    runtime_state=runtime_state,
                    host=api_host,
                    port=api_port,
                    debug=debug,
                    auth_username=auth_username,
                    auth_password_hash=auth_password_hash,
                    auth_session_seconds=(
                        auth_session_seconds
                    ),
                    auth_cookie_secure=(
                        auth_cookie_secure
                    )
                )

                if debug:
                    print(
                        "HTTP API listening on http://{}:{}".format(
                            api_host,
                            api_port
                        )
                    )
                    print(
                        "HTTP API protected endpoints: /api/v1/health, "
                        "/api/v1/overview, /api/v1/history, "
                        "/api/v1/metrics, /api/v1/snapshot"
                    )

            try:
                while True:
                    cycle = run_cycle(
                        config=config,
                        str_to_bool=str_to_bool,
                        registers_file=registers_file,
                        registers=registers,
                        mqtt_client=mqtt,
                        collect_snapshot=collect_snapshot,
                        publish_stable_metrics=(
                            publish_stable_metrics
                        ),
                        runtime_state=runtime_state,
                        profile_name=profile_name,
                        debug=debug
                    )

                    data = cycle["telemetry"]

                    if debug:
                        print(_("Inverter data:"))
                        for key, value in data.items():
                            print(
                                "  {:30}: {}".format(
                                    _(key),
                                    value
                                )
                            )

                    if (
                            mqtt is not None
                            and cycle[
                                "legacy_publish_success"
                            ] is False):
                        print(
                            "MQTT legacy telemetry publication "
                            "was incomplete",
                            file=sys.stderr
                        )

                    metrics_report = cycle[
                        "metrics_publish_result"
                    ]

                    if (
                            metrics_report is not None
                            and not metrics_report["complete"]):
                        print(
                            "MQTT stable metrics publication "
                            "incomplete: {} of {} failed".format(
                                metrics_report[
                                    "metrics_failed"
                                ],
                                metrics_report[
                                    "metrics_total"
                                ]
                            ),
                            file=sys.stderr
                        )

                    if (
                            debug
                            and metrics_report is not None):
                        print(
                            "MQTT stable metrics: {} / {} published".format(
                                metrics_report[
                                    "metrics_published"
                                ],
                                metrics_report[
                                    "metrics_total"
                                ]
                            )
                        )

                    time.sleep(update_interval)

            except KeyboardInterrupt:
                if debug:
                    print(_("Interrupted by user, shutting down..."))
            finally:
                if http_api:
                    http_api.close()

                if mqtt:
                    mqtt.disconnect()

    except Exception as e:
        print(_("Error:"), e, file=sys.stderr)
        sys.exit(1)
    finally:
        release_instance_lock(instance_lock)


if __name__ == "__main__":
    main()
