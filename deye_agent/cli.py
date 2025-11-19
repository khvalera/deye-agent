import argparse
import sys
import time

from .config import load_config, str_to_bool, CONFIG_PATH, REGISTERS_FILE
from .deye_reader import read_deye_data
from .i18n import _
from .alarm_checker import check_alarms
from .registers_loader import load_registers
from .notify_email import send_email
from .notify_matrix import send_matrix_message


def build_arg_parser():
    parser = argparse.ArgumentParser(
        description=_("Deye Agent - Command line tool for retrieving data from Deye inverter"),
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
        "--debug",
        "-d",
        help=_("Enable DEBUG mode"),
        action="store_true"
    )

    # MQTT ON/OFF override
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

    # Test notifications
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

    # Commands
    parser.add_argument(
        "command",
        nargs="?",
        default="read",
        choices=["read", "run"],
        help=_("Command: read - read data once, run - start agent loop")
    )

    return parser


def main():
    parser = build_arg_parser()
    args = parser.parse_args()

    config = load_config(args.config)

    if args.debug:
        config["DEBUG"] = "true"

    # Override MQTT flag
    if args.mqtt_enabled is not None:
        config["MQTT_ENABLED"] = "true" if args.mqtt_enabled else "false"

    debug = str_to_bool(config.get("DEBUG", "false"))

    if debug:
        print(_("Starting Deye Agent..."))
        print(_("Loaded configuration from {}").format(args.config))

    # Determine registers file: CLI > config > default
    if args.registers:
        registers_file = args.registers
    else:
        registers_file = config.get("REGISTERS_FILE", REGISTERS_FILE)

    if debug:
        print(_("Using registers from {}").format(registers_file))

    # Load registers.yaml once
    registers = load_registers(registers_file)

    update_interval = int(config.get("UPDATE_INTERVAL", "60"))

    # --- TEST EMAIL ---
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

    # --- TEST MATRIX ---
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

    # --- READ MODE ---
    try:
        if args.command == "read":
            data = read_deye_data(config, str_to_bool, registers_file)

            print(_("Inverter data:"))
            for key, value in data.items():
                print(f"  {_ (key):30}: {value}")

            check_alarms(data, registers, config, debug=debug)

            if config.get("MQTT_ENABLED", "false").lower() == "true":
                from .mqtt_client import MQTTClient
                mqtt = MQTTClient(config, debug=debug)
                if mqtt.connect():
                    mqtt.publish(data)
                    mqtt.disconnect()

        # --- RUN MODE (daemon via systemd) ---
        elif args.command == "run":
            from .mqtt_client import MQTTClient
            mqtt = None

            # Connect MQTT once at start
            if config.get("MQTT_ENABLED", "false").lower() == "true":
                mqtt = MQTTClient(config, debug=debug)
                if not mqtt.connect():
                    print(_("Failed to connect to MQTT broker, exiting."))
                    sys.exit(1)

            try:
                while True:
                    data = read_deye_data(config, str_to_bool, registers_file)

                    if debug:
                        print(_("Inverter data:"))
                        for key, value in data.items():
                            print(f"  {_ (key):30}: {value}")

                    # Alarm processing
                    check_alarms(data, registers, config, debug=debug)

                    # Publish MQTT
                    if mqtt:
                        mqtt.publish(data)

                    time.sleep(update_interval)

            except KeyboardInterrupt:
                if debug:
                    print(_("Interrupted by user, shutting down..."))
            finally:
                if mqtt:
                    mqtt.disconnect()

    except Exception as e:
        print(_("Error:"), e)
        sys.exit(1)


if __name__ == "__main__":
    main()
