# nodes/brainstem_4070/config.py
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Model + runtime
    model_name: str = "BAAI/bge-large-en-v1.5"
    device: str = "cpu"  # change to "cuda" when you wire in GPU

    # STM buffer
    max_stm_items: int = 1024

    # Service
    host: str = "0.0.0.0"
    port: int = 5001

    log_level: str = "INFO"

    class Config:
        env_prefix = "BRAINSTEM_"
        case_sensitive = False


settings = Settings()
