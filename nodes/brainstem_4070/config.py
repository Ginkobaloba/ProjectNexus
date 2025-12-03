# nodes/brainstem_4070/config.py
import uuid
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Model + runtime
    model_name: str = "BAAI/bge-large-en-v1.5"
    device: str = "cpu"  # change to "cuda" when I wire in GPU

    #Identification for NAS Memory Service
    node_id: str = "brainstem_4070"
    session_id: str = str(uuid.uuid4())

    # STM buffer
    max_stm_items: int = 1024
    stm_limit: int = 20

    # --Nas-- Memory
    nas_url: str = "http://nas_memory:5002"  

    # Service
    host: str = "0.0.0.0"
    port: int = 5001

    log_level: str = "INFO"

    class Config:
        env_prefix = "BRAINSTEM_"
        case_sensitive = False


settings = Settings()
