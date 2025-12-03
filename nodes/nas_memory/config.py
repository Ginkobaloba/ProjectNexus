# nodes/nas-memory/config.py
from pathlib import Path
from pydantic import BaseSettings


class Settings(BaseSettings):
    # Base directory for NAS data (vector DB + episodic logs)
    data_dir: Path = Path("/data/nas")

    # Chroma settings
    chroma_persist_dir: Path = Path("/data/nas/chroma")
    chroma_collection_name: str = "nexus_semantic_memory"

    # Episodic log file
    episodic_log_file: Path = Path("/data/nas/episodic.jsonl")

    # Service
    host: str = "0.0.0.0"
    port: int = 5002
    log_level: str = "INFO"

    class Config:
        env_prefix = "NAS_"
        case_sensitive = False


settings = Settings()

# Ensure directories exist
settings.data_dir.mkdir(parents=True, exist_ok=True)
settings.chroma_persist_dir.mkdir(parents=True, exist_ok=True)
settings.episodic_log_file.parent.mkdir(parents=True, exist_ok=True)
