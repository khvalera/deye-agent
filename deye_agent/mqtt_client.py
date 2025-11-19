
import paho.mqtt.client as mqtt
from .i18n import _

class MQTTClient:
    def __init__(self, config, debug=False):
        self.debug = debug
        self.host = config.get("MQTT_HOST", "127.0.0.1")
        self.port = int(config.get("MQTT_PORT", 1883))
        self.username = config.get("MQTT_USERNAME", None)
        self.password = config.get("MQTT_PASSWORD", None)
        self.topic_base = config.get("MQTT_TOPIC", "solar/deye")

        self.client = mqtt.Client(protocol=mqtt.MQTTv311)

        if self.username and self.password:
            self.client.username_pw_set(self.username, self.password)

    def connect(self):
        try:
            self.client.connect(self.host, self.port, keepalive=60)
            if self.debug:
                print(_("Connected to MQTT broker"))
            return True
        except Exception as e:
            print(_("MQTT connection error:"), e)
            return False

    def publish(self, data):
        """Always publish all keys — no skipping."""
        for key, value in data.items():
            topic_key = key.replace(" ", "_")
            full_topic = f"{self.topic_base}/{topic_key}"
            payload = str(value)

            try:
                result = self.client.publish(full_topic, payload)
                if self.debug:
                    if result.rc == 0:
                        print(
                            _("Published data to topic '{topic}': {payload}").format(
                                topic=full_topic, payload=payload
                            )
                        )
                    else:
                        print(
                            _("Failed to publish to topic '{topic}': return code {rc}").format(
                                topic=full_topic, rc=result.rc
                            )
                        )
            except Exception as e:
                print(_("Error publishing to topic '{topic}': {error}").format(
                    topic=full_topic, error=e))

    def disconnect(self):
        self.client.disconnect()
        if self.debug:
            print(_("Disconnected from MQTT broker"))
