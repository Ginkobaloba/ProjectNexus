from pydantic import BaseSettings


class CoreSettings(BaseSettings):
    app_name: str = "Nexus Core"
    mqtt_broker_host: str = "localhost"
    mqtt_broker_port: int = 1883
    mqtt_keepalive: int = 60
    heartbeat_topic: str = "nexus/heartbeat"
    command_topic_prefix: str = "nexus/agents"
    log_level: str = "INFO"

    class Config:
        env_prefix = "NEXUS_"
        env_file = ".env"


settings = CoreSettings()
