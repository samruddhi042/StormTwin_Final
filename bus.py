"""Message bus: real MQTT (paho) or an in-process fallback with the same interface."""
import json, re, threading


class LocalBus:
    """In-process pub/sub with MQTT-style '+' and '#' wildcards. No broker needed."""
    def __init__(self):
        self.subs = []
    def subscribe(self, pattern, cb):
        rx = "^" + re.escape(pattern).replace(r"\+", "[^/]+").replace(r"\#", ".*") + "$"
        self.subs.append((re.compile(rx), cb))
    def publish(self, topic, payload):
        for rx, cb in self.subs:
            if rx.match(topic):
                cb(topic, payload if isinstance(payload, dict) else json.loads(payload))
    def close(self):
        pass


class MqttBus:
    """Thin wrapper around paho-mqtt (Mosquitto etc.). Payloads are JSON."""
    def __init__(self, host="localhost", port=1883, client_id=""):
        import paho.mqtt.client as mqtt
        self.c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
        self._cbs = []
        self.c.on_message = self._on_message
        self.c.connect(host, port, 60)
        self.c.loop_start()
    def _on_message(self, client, userdata, msg):
        data = json.loads(msg.payload.decode())
        for rx, cb in self._cbs:
            if rx.match(msg.topic):
                cb(msg.topic, data)
    def subscribe(self, pattern, cb):
        rx = "^" + re.escape(pattern).replace(r"\+", "[^/]+").replace(r"\#", ".*") + "$"
        self._cbs.append((re.compile(rx), cb))
        self.c.subscribe(pattern, qos=1)
    def publish(self, topic, payload):
        self.c.publish(topic, json.dumps(payload), qos=1)
    def close(self):
        self.c.loop_stop(); self.c.disconnect()


def make_bus(kind="local", **kw):
    return MqttBus(**kw) if kind == "mqtt" else LocalBus()
