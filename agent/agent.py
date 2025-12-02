import json
import time
from datetime import datetime
from typing import Any

import paho.mqtt.client as mqtt

from .config import settings


class NexusAgent:
    def __init__(self):
        self.settings = settings
        self.client = mqtt.Client()
        self.client.on_connect = self.on_connect

    def on_connect(self, client: mqtt.Client, userdata: Any, flags: dict, rc: int):
        if rc == 0:
            print(
                f"[{self.settings.agent_id}] Connected to MQTT broker "
                f"at {self.settings.mqtt_broker_host}:{self.settings.mqtt_broker_port}"
            )
        else:
            print(f"[{self.settings.agent_id}] Failed to connect to MQTT broker (rc={rc})")

    def send_heartbeat(self):
        payload = {
            "agent_id": self.settings.agent_id,
            "role": self.settings.role,
            "host": self.settings.host_name,
            "timestamp": datetime.utcnow().isoformat(),
            "status": "online",
            "meta": {},
        }

        self.client.publish(self.settings.heartbeat_topic, json.dumps(payload))
        print(f"[{self.settings.agent_id}] → Heartbeat sent")

    def run(self):
        # Connect to broker
        self.client.connect(
            self.settings.mqtt_broker_host,
            self.settings.mqtt_broker_port,
            self.settings.mqtt_keepalive,
        )

        self.client.loop_start()

        try:
            while True:
                self.send_heartbeat()
                time.sleep(self.settings.heartbeat_interval)

        except KeyboardInterrupt:
            print(f"[{self.settings.agent_id}] Shutdown requested")

        finally:
            self.client.loop_stop()
            self.client.disconnect()


if __name__ == "__main__":
    NexusAgent().run()
