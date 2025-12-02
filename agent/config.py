from pydantic import BaseSettings
from socket import gethostname


class AgentSettings(BaseSettings):
    agent_id: str = "agent-1"
    role: str = "generic"
    mqtt_broker_host: str = "localhost"
    mqtt_broker_port: int = 1883
    mqtt_keepalive: int = 60
    heartbeat_topic: str = "nexus/heartbeat"
    heartbeat_interval: int = 10  # seconds

    host_name: str = gethostname()

    class Config:
        env_prefix = "NEXUS_AGENT_"
        env_file = ".env"


settings = AgentSettings()
