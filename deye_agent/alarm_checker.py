from .notify_email import send_email
from .notify_matrix import send_matrix_message
from .i18n import _


# Dictionary for saving active alarm status in process memory.
alarm_state = {}

# Number of consecutive valid abnormal samples seen for each register.
# This state is process-local and is therefore intended for the long-running
# "run" mode used by systemd.
alarm_pending_count = {}


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


def check_alarms(data, registers, config, debug=False):
    alarm_confirmations = _get_alarm_confirmations(config, debug=debug)

    for reg in registers:
        name = reg.get("name")

        # Thresholds
        alarm_threshold = reg.get("alarm")
        cancel_threshold = reg.get(
            "cancel",
            (alarm_threshold + 5) if alarm_threshold is not None else None
        )

        # Emojis
        alarm_emoji = reg.get("alarm_emoji", "⚠ ")
        cancel_emoji = reg.get("cancel_emoji", "✅")

        if alarm_threshold is None:
            continue  # Skip if no alarm set

        value = data.get(name)
        if value is None:
            # Missing/invalid reads are ignored. They neither confirm an alarm
            # nor reset a confirmation sequence.
            continue

        # Translate parameter name for notifications.
        name_translated = _(name)

        # ===== ALARM TRIGGER =====
        if value <= alarm_threshold:

            # An already active alarm does not need further confirmation.
            if alarm_state.get(name, False):
                alarm_pending_count[name] = 0
                continue

            pending_count = alarm_pending_count.get(name, 0) + 1
            alarm_pending_count[name] = pending_count

            if pending_count < alarm_confirmations:
                if debug:
                    print(
                        "DEBUG: Alarm confirmation for {}: {}/{} "
                        "(value={}, threshold={})".format(
                            name,
                            pending_count,
                            alarm_confirmations,
                            value,
                            alarm_threshold
                        )
                    )
                continue

            subject = _("{emoji} Alarm: {name} below threshold").format(
                emoji=alarm_emoji,
                name=name_translated
            )
            body = _(
                "{emoji} {name} value {value} is below alarm threshold "
                "{threshold}"
            ).format(
                emoji=alarm_emoji,
                name=name_translated,
                value=value,
                threshold=alarm_threshold
            )

            try:
                # Email
                if config.get("NOTIFY_EMAIL_ENABLED", "false").lower() == "true":
                    send_email(config, subject, body, debug=debug)

                # Matrix
                if config.get("NOTIFY_MATRIX_ENABLED", "false").lower() == "true":
                    send_matrix_message(config, message=body, debug=debug)

                alarm_state[name] = True
                alarm_pending_count[name] = 0

                if debug:
                    print(
                        "DEBUG: Sent alarm notification for {} after "
                        "{}/{} confirmation(s)".format(
                            name,
                            alarm_confirmations,
                            alarm_confirmations
                        )
                    )

            except Exception as e:
                # Keep the pending count at the confirmation threshold so the
                # next valid abnormal sample can retry the notification.
                alarm_pending_count[name] = alarm_confirmations

                if debug:
                    print(
                        "DEBUG: Failed to send alarm notification: {}".format(e)
                    )

        # ===== ALARM CANCEL =====
        elif (
            alarm_state.get(name, False)
            and cancel_threshold is not None
            and value >= cancel_threshold
        ):

            subject = _(
                "{emoji} Alarm cleared: {name} back to normal"
            ).format(
                emoji=cancel_emoji,
                name=name_translated
            )
            body = _(
                "{emoji} {name} value {value} exceeded the alarm "
                "cancellation threshold {threshold}"
            ).format(
                emoji=cancel_emoji,
                name=name_translated,
                value=value,
                threshold=cancel_threshold
            )

            try:
                # Email
                if config.get("NOTIFY_EMAIL_ENABLED", "false").lower() == "true":
                    send_email(config, subject, body, debug=debug)

                # Matrix
                if config.get("NOTIFY_MATRIX_ENABLED", "false").lower() == "true":
                    send_matrix_message(config, message=body, debug=debug)

                alarm_state[name] = False
                alarm_pending_count[name] = 0

                if debug:
                    print(
                        "DEBUG: Sent alarm cleared notification for {}".format(
                            name
                        )
                    )

            except Exception as e:
                if debug:
                    print(
                        "DEBUG: Failed to send alarm cleared notification: {}".format(
                            e
                        )
                    )

        else:
            # Any valid non-alarm sample breaks a pending confirmation
            # sequence while the alarm is not active.
            if not alarm_state.get(name, False):
                if alarm_pending_count.get(name, 0) and debug:
                    print(
                        "DEBUG: Reset alarm confirmation for {} after "
                        "normal value {}".format(name, value)
                    )

                alarm_pending_count[name] = 0
