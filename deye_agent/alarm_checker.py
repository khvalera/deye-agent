import datetime
import json
import os
import sys

from .alarms import get_alarm_rules
from .config import ALARMS_FILE
from .notify_email import send_email
from .notify_matrix import send_matrix_message
from .notify_mqtt import send_mqtt_notification
from .i18n import _


# Dictionary for saving active alarm status in process memory.
alarm_state = {}

# Number of consecutive valid abnormal samples seen for each alarm rule.
# This state is process-local and is therefore intended for the long-running
# "run" mode used by systemd.
alarm_pending_count = {}


TELEMETRY_CACHE_PATH = "/run/deye-agent/telemetry.json"
TELEMETRY_CACHE_SCHEMA = "deye-agent.telemetry-cache.v1"


def _utc_now_iso():
    """Return a compact UTC timestamp compatible with Python 3.6."""
    return (
        datetime.datetime.utcnow()
        .replace(microsecond=0)
        .isoformat()
        + "Z"
    )


def _write_telemetry_cache(data, registers, config, debug=False):
    """Persist the daemon's already-acquired telemetry for local consumers.

    This cache never performs serial/Modbus access. It only mirrors the data
    already passed to check_alarms() by the running daemon. Failure to update
    the cache must never interrupt polling or alarm processing.
    """
    if not isinstance(data, dict):
        return

    register_index = {}
    for register in registers or []:
        if not isinstance(register, dict):
            continue
        name = register.get("name")
        if name:
            register_index[name] = register

    values = {}
    for name, value in data.items():
        register = register_index.get(name, {})
        values[str(name)] = {
            "value": value,
            "unit": register.get("unit") or "",
        }

    document = {
        "schema": TELEMETRY_CACHE_SCHEMA,
        "schema_version": 1,
        "read_only": True,
        "profile": str(config.get("PROFILE", "")).strip(),
        "updated_at": _utc_now_iso(),
        "values": values,
    }

    directory = os.path.dirname(TELEMETRY_CACHE_PATH)
    temporary_path = (
        TELEMETRY_CACHE_PATH
        + ".tmp."
        + str(os.getpid())
    )

    try:
        if os.path.islink(directory):
            raise RuntimeError("telemetry cache directory must not be a symlink")

        if not os.path.isdir(directory):
            os.makedirs(directory, mode=0o755)

        with open(temporary_path, "w", encoding="utf-8") as handle:
            json.dump(
                document,
                handle,
                ensure_ascii=False,
                sort_keys=False,
                separators=(",", ":")
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, TELEMETRY_CACHE_PATH)

    except Exception as exc:
        try:
            if os.path.exists(temporary_path):
                os.unlink(temporary_path)
        except OSError:
            pass

        if debug:
            print(
                "DEBUG: Unable to update telemetry cache {}: {}".format(
                    TELEMETRY_CACHE_PATH,
                    exc
                )
            )


def _get_alarm_confirmations(config, debug=False):
    """Return the required number of consecutive abnormal samples."""
    default_confirmations = 2
    raw_value = config.get("ALARM_CONFIRMATIONS", str(default_confirmations))

    try:
        confirmations = int(raw_value)
        if confirmations < 1:
            raise ValueError
    except (TypeError, ValueError):
        confirmations = default_confirmations

        if debug:
            print(
                "DEBUG: Invalid ALARM_CONFIRMATIONS {!r}; using {}".format(
                    raw_value,
                    confirmations
                )
            )

    return confirmations


def _is_numeric(value):
    # bool_any_nonzero metrics intentionally produce True/False.
    # Python booleans compare numerically as 1/0, so allow them in threshold
    # rules such as Has Fault >= 1 and clear <= 0.
    return isinstance(value, (int, float))


def _is_alarm_value(operator, value, threshold):
    if operator == "le":
        return value <= threshold
    return value >= threshold


def _is_clear_value(operator, value, threshold):
    if operator == "le":
        return value >= threshold
    return value <= threshold


def _render_message(template, context):
    """Render only the documented literal placeholders.

    Deliberately avoid str.format() so user-controlled templates cannot perform
    attribute/index traversal. Unknown placeholders are left unchanged.
    """
    rendered = template

    for key in (
            "name",
            "value",
            "unit",
            "alarm",
            "cancel",
            "profile"):
        rendered = rendered.replace(
            "{" + key + "}",
            str(context.get(key, ""))
        )

    return rendered


def _default_trigger_text(operator, name, value, alarm_threshold):
    if operator == "le":
        subject = _("{emoji} Alarm: {name} below threshold").format(
            emoji="⚠",
            name=name
        )
        body = _(
            "{emoji} {name} value {value} is below alarm threshold "
            "{threshold}"
        ).format(
            emoji="⚠",
            name=name,
            value=value,
            threshold=alarm_threshold
        )
    else:
        subject = _("{emoji} Alarm: {name} above threshold").format(
            emoji="⚠",
            name=name
        )
        body = _(
            "{emoji} {name} value {value} is above alarm threshold "
            "{threshold}"
        ).format(
            emoji="⚠",
            name=name,
            value=value,
            threshold=alarm_threshold
        )

    return subject, body


def _default_clear_text(operator, name, value, cancel_threshold):
    subject = _(
        "{emoji} Alarm cleared: {name} back to normal"
    ).format(
        emoji="✅",
        name=name
    )

    if operator == "le":
        body = _(
            "{emoji} {name} value {value} exceeded the alarm "
            "cancellation threshold {threshold}"
        ).format(
            emoji="✅",
            name=name,
            value=value,
            threshold=cancel_threshold
        )
    else:
        body = _(
            "{emoji} {name} value {value} dropped below the alarm "
            "cancellation threshold {threshold}"
        ).format(
            emoji="✅",
            name=name,
            value=value,
            threshold=cancel_threshold
        )

    return subject, body


def _send_notification(config, subject, body, debug=False):
    """Send text notification channels (Email and Matrix)."""
    if config.get("NOTIFY_EMAIL_ENABLED", "false").lower() == "true":
        send_email(config, subject, body, debug=debug)

    if config.get("NOTIFY_MATRIX_ENABLED", "false").lower() == "true":
        send_matrix_message(config, message=body, debug=debug)


def _mqtt_enabled(config):
    return config.get("NOTIFY_MQTT_ENABLED", "false").lower() == "true"


def _build_mqtt_event(
        event_type,
        rule,
        profile,
        name,
        value,
        unit,
        message):
    return {
        "event": event_type,
        "profile": profile,
        "rule_id": rule["id"],
        "name": name,
        "value": value,
        "unit": unit,
        "operator": rule["operator"],
        "alarm": rule["alarm"],
        "cancel": rule["cancel"],
        "message": message,
    }


def check_alarms(data, registers, config, debug=False):
    _write_telemetry_cache(data, registers, config, debug=debug)

    alarm_confirmations = _get_alarm_confirmations(config, debug=debug)
    alarms_file = str(
        config.get("ALARMS_FILE", ALARMS_FILE)
    ).strip() or ALARMS_FILE

    rules, load_error, changed = get_alarm_rules(alarms_file)

    if load_error:
        alarm_state.clear()
        alarm_pending_count.clear()

        if changed:
            print(
                "Warning: unable to load alarm rules from {}: {}".format(
                    alarms_file,
                    load_error
                ),
                file=sys.stderr
            )
        return

    register_index = {}
    for register in registers or []:
        name = register.get("name")
        if name:
            register_index[name] = register

    active_rule_ids = set()

    for rule in rules:
        rule_id = rule["id"]

        if not rule["enabled"]:
            alarm_state.pop(rule_id, None)
            alarm_pending_count.pop(rule_id, None)
            continue

        active_rule_ids.add(rule_id)

        metric = rule["metric"]
        register = register_index.get(metric)

        if register is None:
            if debug:
                print(
                    "DEBUG: Alarm rule '{}' ignored: metric '{}' is not "
                    "present in the active register map".format(
                        rule_id,
                        metric
                    )
                )
            continue

        value = data.get(metric)
        if value is None:
            continue

        if not _is_numeric(value):
            if debug:
                print(
                    "DEBUG: Alarm rule '{}' ignored non-numeric value {!r} "
                    "for metric '{}'".format(
                        rule_id,
                        value,
                        metric
                    )
                )
            continue

        operator = rule["operator"]
        alarm_threshold = rule["alarm"]
        cancel_threshold = rule["cancel"]
        name_translated = _(metric)
        unit = register.get("unit") or ""
        profile = str(config.get("PROFILE", "")).strip()

        context = {
            "name": name_translated,
            "value": value,
            "unit": unit,
            "alarm": alarm_threshold,
            "cancel": cancel_threshold,
            "profile": profile,
        }

        # ===== ALARM TRIGGER =====
        if _is_alarm_value(operator, value, alarm_threshold):
            if alarm_state.get(rule_id, False):
                alarm_pending_count[rule_id] = 0
                continue

            pending_count = alarm_pending_count.get(rule_id, 0) + 1
            alarm_pending_count[rule_id] = pending_count

            if pending_count < alarm_confirmations:
                if debug:
                    print(
                        "DEBUG: Alarm confirmation for {}: {}/{} "
                        "(value={}, threshold={})".format(
                            rule_id,
                            pending_count,
                            alarm_confirmations,
                            value,
                            alarm_threshold
                        )
                    )
                continue

            subject, default_body = _default_trigger_text(
                operator,
                name_translated,
                value,
                alarm_threshold
            )
            body = (
                _render_message(rule["message"], context)
                if rule["message"]
                else default_body
            )

            try:
                _send_notification(
                    config,
                    subject,
                    body,
                    debug=debug
                )

                if _mqtt_enabled(config):
                    send_mqtt_notification(
                        config,
                        _build_mqtt_event(
                            "alarm",
                            rule,
                            profile,
                            metric,
                            value,
                            unit,
                            body
                        ),
                        debug=debug
                    )

                alarm_state[rule_id] = True
                alarm_pending_count[rule_id] = 0

                if debug:
                    print(
                        "DEBUG: Sent alarm notification for {} after "
                        "{}/{} confirmation(s)".format(
                            rule_id,
                            alarm_confirmations,
                            alarm_confirmations
                        )
                    )

            except Exception as exc:
                # Keep the pending count at the confirmation threshold so the
                # next valid abnormal sample can retry the notification.
                alarm_pending_count[rule_id] = alarm_confirmations

                if debug:
                    print(
                        "DEBUG: Failed to send alarm notification: {}".format(
                            exc
                        )
                    )

        # ===== ALARM CLEAR =====
        elif (
            alarm_state.get(rule_id, False)
            and _is_clear_value(operator, value, cancel_threshold)
        ):
            subject, default_body = _default_clear_text(
                operator,
                name_translated,
                value,
                cancel_threshold
            )
            body = (
                _render_message(rule["clear_message"], context)
                if rule["clear_message"]
                else default_body
            )

            try:
                _send_notification(
                    config,
                    subject,
                    body,
                    debug=debug
                )

                if _mqtt_enabled(config):
                    send_mqtt_notification(
                        config,
                        _build_mqtt_event(
                            "clear",
                            rule,
                            profile,
                            metric,
                            value,
                            unit,
                            body
                        ),
                        debug=debug
                    )

                alarm_state[rule_id] = False
                alarm_pending_count[rule_id] = 0

                if debug:
                    print(
                        "DEBUG: Sent alarm cleared notification for {}".format(
                            rule_id
                        )
                    )

            except Exception as exc:
                if debug:
                    print(
                        "DEBUG: Failed to send alarm cleared notification: "
                        "{}".format(exc)
                    )

        else:
            # Any valid non-alarm sample breaks a pending confirmation
            # sequence while the alarm is not active.
            if not alarm_state.get(rule_id, False):
                if alarm_pending_count.get(rule_id, 0) and debug:
                    print(
                        "DEBUG: Reset alarm confirmation for {} after "
                        "normal value {}".format(rule_id, value)
                    )

                alarm_pending_count[rule_id] = 0

    # Forget state for rules that were removed from the file.
    for rule_id in list(alarm_state):
        if rule_id not in active_rule_ids:
            alarm_state.pop(rule_id, None)

    for rule_id in list(alarm_pending_count):
        if rule_id not in active_rule_ids:
            alarm_pending_count.pop(rule_id, None)
