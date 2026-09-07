import json

from .mqtt_client import MQTTClient


ALARM_MQTT_SCHEMA = "deye-agent.alarm.v1"


def _notification_topic(config):
    configured = str(config.get("NOTIFY_MQTT_TOPIC", "")).strip()

    if configured:
        topic = configured
    else:
        base = str(config.get("MQTT_TOPIC", "solar/deye")).strip().rstrip("/")
        if not base:
            base = "solar/deye"
        topic = "{}/alarms".format(base)

    if "\x00" in topic or "+" in topic or "#" in topic:
        raise ValueError(
            "NOTIFY_MQTT_TOPIC must be a publish topic without wildcards"
        )

    return topic


def build_alarm_payload(event):
    """Build the stable MQTT JSON document for one alarm event."""
    if not isinstance(event, dict):
        raise ValueError("alarm event must be a dictionary")

    event_type = event.get("event")
    if event_type not in ("alarm", "clear"):
        raise ValueError("alarm event type must be 'alarm' or 'clear'")

    return {
        "schema": ALARM_MQTT_SCHEMA,
        "event": event_type,
        "profile": str(event.get("profile", "")),
        "rule_id": str(event.get("rule_id", "")),
        "name": str(event.get("name", "")),
        "value": event.get("value"),
        "unit": str(event.get("unit", "")),
        "operator": str(event.get("operator", "")),
        "alarm": event.get("alarm"),
        "cancel": event.get("cancel"),
        "message": str(event.get("message", "")),
    }


def send_mqtt_notification(config, event, debug=False):
    """Publish one threshold notification through the configured MQTT broker.

    MQTT host, port and credentials are shared with the existing MQTT transport.
    NOTIFY_MQTT_TOPIC controls only the alarm-event destination topic.
    """
    topic = _notification_topic(config)
    document = build_alarm_payload(event)
    payload = json.dumps(
        document,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=False
    )

    client = MQTTClient(config, debug=debug)

    if not client.connect():
        raise RuntimeError("unable to connect to MQTT broker for notification")

    try:
        if not client.publish_topic(topic, payload):
            raise RuntimeError(
                "unable to publish MQTT notification to '{}'".format(topic)
            )
    finally:
        client.disconnect()

    return {
        "topic": topic,
        "payload": document,
    }
