
from .notify_email import send_email
from .notify_matrix import send_matrix_message
from .i18n import _

# Dictionary for saving alarm status (in process memory)
alarm_state = {}

def check_alarms(data, registers, config, debug=False):
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
            continue

        # Перекладаємо ім'я параметра для повідомлень
        name_translated = _(name)

        # ===== ALARM TRIGGER =====
        if value <= alarm_threshold:

            # Alarm was NOT active before → trigger
            if not alarm_state.get(name, False):

                subject = _("{emoji} Alarm: {name} below threshold").format(
                    emoji=alarm_emoji,
                    name=name_translated
                )
                body = _("{emoji} {name} value {value} is below alarm threshold {threshold}").format(
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

                    if debug:
                        print(f"DEBUG: Sent alarm notification for {name}")

                except Exception as e:
                    if debug:
                        print(f"DEBUG: Failed to send alarm notification: {e}")

        # ===== ALARM CANCEL =====
        elif alarm_state.get(name, False) and cancel_threshold is not None and value >= cancel_threshold:

            subject = _("{emoji} Alarm cleared: {name} back to normal").format(
                emoji=cancel_emoji,
                name=name_translated
            )
            body = _("{emoji} {name} value {value} exceeded the alarm cancellation threshold {threshold}").format(
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

                if debug:
                    print(f"DEBUG: Sent alarm cleared notification for {name}")

            except Exception as e:
                if debug:
                    print(f"DEBUG: Failed to send alarm cleared notification: {e}")
