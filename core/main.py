import json
from datetime import datetime
from typing import Any

import paho.mqtt.client as mqtt

from .config import settings
from .logging_config import get_logger
from .registry import AgentRegistry
from .models import Heartbeat

logger = get_logger("nexus.core")
registry = AgentRegistry()


def on_connect(client: mqtt.Client, userdata: Any, flags: dict, rc: int):
    if rc == 0:
        logger.info(f"Connected to MQTT at {settings.mqtt_broker_host}:{settings.mqtt_broker_port}")
        client.subscribe(settings.heartbeat_topic)
        logger.info(f"Subscribed → {settings.heartbeat_topic}")
    else:
        logger.error(f"Failed to connect to MQTT broker (rc={rc})")


def on_message(client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage):
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
        logger.debug(f"Received on {msg.topic}: {payload}")

        if msg.topic == settings.heartbeat_topic:
            heartbeat = Heartbeat(**payload)
            registry.update_heartbeat(heartbeat.agent_id, payload)

            logger.info(
                f"Heartbeat ← {heartbeat.agent_id} "
                f"(role={heartbeat.role}, host={heartbeat.host}, status={heartbeat.status})"
            )

    except Exception as e:
        logger.exception(f"Error processing MQTT message on {msg.topic}: {e}")


def print_active_agents():
    active = registry.get_active_agents()

    if not active:
        logger.info("No active agents yet…")
        return

    logger.info("🟢 Active agents:")
    for agent_id, info in active.items():
        ts = info["last_seen"].isoformat()
        role = info["payload"].get("role")
        logger.info(f"  - {agent_id} (role={role}, last_seen={ts})")


def main():
    logger.info(f"🌐 Starting {settings.app_name}…")

    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(settings.mqtt_broker_host, settings.mqtt_broker_port, settings.mqtt_keepalive)

    client.loop_start()

    try:
        while True:
            print_active_agents()
            import time
            time.sleep(15)
    except KeyboardInterrupt:
        logger.info("Shutdown requested…")
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
