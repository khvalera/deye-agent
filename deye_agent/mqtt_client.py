import json
import threading

import paho.mqtt.client as mqtt

from .i18n import _


MQTT_PUBLISH_SCHEMA = "deye-agent.mqtt-publish.v1"


class MQTTClient:
    """Small reliable MQTT wrapper for Deye Agent.

    Compatibility goals:
    - keep the existing MQTT_HOST/MQTT_PORT/MQTT_USERNAME/MQTT_PASSWORD/
      MQTT_TOPIC configuration contract;
    - keep legacy publish(data) topic naming for read/run;
    - add stable metrics publication without changing metrics read behavior.

    Transport goals:
    - run the paho network loop;
    - wait for CONNACK before reporting a successful connection;
    - wait for each publish callback before treating a message as sent;
    - use bounded waits so broker/network problems do not block forever.
    """

    def __init__(self, config, debug=False):
        self.debug = debug

        self.host = config.get("MQTT_HOST", "127.0.0.1")
        self.port = int(config.get("MQTT_PORT", 1883))
        self.username = config.get("MQTT_USERNAME", None)
        self.password = config.get("MQTT_PASSWORD", None)
        self.topic_base = str(
            config.get("MQTT_TOPIC", "solar/deye")
        ).rstrip("/")

        self.connect_timeout = float(
            config.get("MQTT_CONNECT_TIMEOUT", 5.0)
        )
        self.publish_timeout = float(
            config.get("MQTT_PUBLISH_TIMEOUT", 5.0)
        )

        if self.connect_timeout <= 0:
            self.connect_timeout = 5.0
        if self.publish_timeout <= 0:
            self.publish_timeout = 5.0

        self.client = mqtt.Client(protocol=mqtt.MQTTv311)

        if self.username and self.password:
            self.client.username_pw_set(
                self.username,
                self.password
            )

        self._loop_started = False
        self._connected = False
        self._last_connect_rc = None

        self._connect_event = threading.Event()
        self._disconnect_event = threading.Event()

        self._publish_lock = threading.Lock()
        self._publish_events = {}
        self._published_before_wait = set()

        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_publish = self._on_publish

    def _on_connect(self, client, userdata, flags, rc):
        self._last_connect_rc = rc
        self._connected = (rc == 0)
        self._connect_event.set()

    def _on_disconnect(self, client, userdata, rc):
        self._connected = False
        self._disconnect_event.set()

    def _on_publish(self, client, userdata, mid):
        with self._publish_lock:
            event = self._publish_events.get(mid)

            if event is not None:
                event.set()
            else:
                # QoS 0 can complete very quickly. Preserve the callback if it
                # wins the race with registration of the wait event.
                self._published_before_wait.add(mid)

    def _start_loop(self):
        if self._loop_started:
            return

        self.client.loop_start()
        self._loop_started = True

    def _stop_loop(self):
        if not self._loop_started:
            return

        try:
            self.client.loop_stop()
        finally:
            self._loop_started = False

    def connect(self):
        """Connect and wait for broker CONNACK."""
        self._connect_event.clear()
        self._disconnect_event.clear()
        self._connected = False
        self._last_connect_rc = None

        try:
            rc = self.client.connect(
                self.host,
                self.port,
                keepalive=60
            )

            if rc != mqtt.MQTT_ERR_SUCCESS:
                print(
                    _(
                        "MQTT connection error: connect returned code {}"
                    ).format(rc)
                )
                return False

            self._start_loop()

            if not self._connect_event.wait(self.connect_timeout):
                print(
                    _(
                        "MQTT connection error: timed out waiting for CONNACK"
                    )
                )
                self._stop_loop()
                return False

            if not self._connected:
                print(
                    _(
                        "MQTT connection error: broker rejected connection "
                        "with code {}"
                    ).format(self._last_connect_rc)
                )
                self._stop_loop()
                return False

            if self.debug:
                print(_("Connected to MQTT broker"))

            return True

        except Exception as exc:
            print(_("MQTT connection error:"), exc)

            try:
                self._stop_loop()
            except Exception:
                pass

            return False

    def _wait_for_publish(self, info):
        """Wait for paho on_publish for one queued message."""
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            return False

        event = threading.Event()

        with self._publish_lock:
            if info.mid in self._published_before_wait:
                self._published_before_wait.remove(info.mid)
                return True

            self._publish_events[info.mid] = event

        try:
            return event.wait(self.publish_timeout)
        finally:
            with self._publish_lock:
                self._publish_events.pop(info.mid, None)
                self._published_before_wait.discard(info.mid)

    def publish_topic(self, topic, payload):
        """Publish one scalar/string payload and wait for network completion."""
        if not self._connected:
            if self.debug:
                print(
                    _(
                        "Cannot publish to topic '{topic}': "
                        "MQTT is not connected"
                    ).format(topic=topic)
                )
            return False

        try:
            info = self.client.publish(
                topic,
                payload,
                qos=0,
                retain=False
            )

            success = self._wait_for_publish(info)

            if self.debug:
                if success:
                    print(
                        _(
                            "Published data to topic '{topic}': {payload}"
                        ).format(
                            topic=topic,
                            payload=payload
                        )
                    )
                else:
                    print(
                        _(
                            "Failed to publish to topic '{topic}': "
                            "publish acknowledgement timeout or error"
                        ).format(topic=topic)
                    )

            return success

        except Exception as exc:
            print(
                _(
                    "Error publishing to topic '{topic}': {error}"
                ).format(
                    topic=topic,
                    error=exc
                )
            )
            return False

    def publish(self, data):
        """Publish legacy telemetry topics without changing their names.

        Existing mapping is preserved:
          "Grid Voltage" -> <MQTT_TOPIC>/Grid_Voltage
        """
        success = True

        for key, value in data.items():
            topic_key = key.replace(" ", "_")
            full_topic = "{}/{}".format(
                self.topic_base,
                topic_key
            )
            payload = str(value)

            if not self.publish_topic(full_topic, payload):
                success = False

        return success

    @staticmethod
    def _metric_payload(metric):
        if not metric.get("available", False):
            return "null"

        value = metric.get("value")

        if isinstance(value, bool):
            return "true" if value else "false"

        if isinstance(value, (int, float)):
            return json.dumps(
                value,
                ensure_ascii=True,
                separators=(",", ":")
            )

        if value is None:
            return "null"

        return str(value)

    def publish_metrics(self, metrics_document):
        """Publish all stable metrics-v1 IDs as individual MQTT topics.

        Topic contract:
          <MQTT_TOPIC>/metrics/<stable.metric.id>

        The metric ID is preserved exactly as the final topic component.
        Unavailable metrics are published as the literal payload "null".
        """
        if not isinstance(metrics_document, dict):
            raise ValueError(
                "metrics document must be a dictionary"
            )

        if (
                metrics_document.get("schema")
                != "deye-agent.metrics.v1"):
            raise ValueError(
                "publish_metrics requires deye-agent.metrics.v1"
            )

        metrics = metrics_document.get("metrics")

        if not isinstance(metrics, dict):
            raise ValueError(
                "metrics document is missing metrics dictionary"
            )

        topic_root = "{}/metrics".format(
            self.topic_base
        )

        failures = []
        published = 0

        for metric_id in sorted(metrics):
            metric = metrics[metric_id]
            topic = "{}/{}".format(
                topic_root,
                metric_id
            )
            payload = self._metric_payload(metric)

            if self.publish_topic(topic, payload):
                published += 1
            else:
                failures.append({
                    "metric_id": metric_id,
                    "topic": topic,
                })

        return {
            "schema": MQTT_PUBLISH_SCHEMA,
            "schema_version": 1,
            "metrics_schema": metrics_document.get("schema"),
            "profile": metrics_document.get("profile"),
            "topic_root": topic_root,
            "qos": 0,
            "retain": False,
            "metrics_total": len(metrics),
            "metrics_published": published,
            "metrics_failed": len(failures),
            "complete": len(failures) == 0,
            "failures": failures,
        }

    def disconnect(self):
        """Disconnect cleanly and stop the paho network loop."""
        try:
            if self._loop_started:
                self._disconnect_event.clear()

                try:
                    self.client.disconnect()
                finally:
                    self._disconnect_event.wait(
                        min(self.connect_timeout, 2.0)
                    )
        finally:
            self._connected = False
            self._stop_loop()

        if self.debug:
            print(_("Disconnected from MQTT broker"))
