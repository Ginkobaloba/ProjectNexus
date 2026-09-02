# nodes/model_manager_4090/config.py
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # --- Weight tiers (V2 doc Section 7) --------------------------------
    # llama.cpp does NOT tier for us — mmap off the HDD pages miserably —
    # so the manager stages weights hot before any load. Paths are the
    # 4090 host's mounts; tests point these at tmp dirs.
    hot_dir: str = "D:/family_weights/hot"      # 2TB Gen4 NVMe
    warm_dir: str = "E:/family_weights/warm"    # 1TB Gen2 NVMe
    cold_dir: str = "Z:/family_weights/cold"    # 6TB HDD / NAS share

    # --- llama.cpp runtime ----------------------------------------------
    llama_server_bin: str = "llama-server"
    llama_port: int = 8000
    llama_host: str = "127.0.0.1"
    # Seconds to wait for llama-server to answer /health after spawn.
    # A 30B GGUF off Gen4 NVMe loads in well under this; the generous
    # ceiling covers vram_ram_ssd offload policies.
    load_timeout_seconds: float = 600.0
    health_poll_interval_seconds: float = 2.0

    # --- Hub reporting ----------------------------------------------------
    # The manager owns presence (Card 4): waking on load start, awake on
    # healthy, asleep on unload. Token is a normal brainstem bearer token
    # minted for this service.
    hub_url: str = "http://192.168.1.141:5001"
    hub_token: str = ""

    # --- Registry ---------------------------------------------------------
    # Same file the hub boots from; relative resolves against repo root.
    family_registry_path: str = "family/registry.yaml"

    # --- Metrics ------------------------------------------------------------
    metrics_path: str = "/data/metrics/model_manager_metrics.jsonl"

    # --- Service -----------------------------------------------------------
    host: str = "0.0.0.0"
    port: int = 5004
    log_level: str = "INFO"

    class Config:
        env_prefix = "MODELMGR_"
        case_sensitive = False


settings = Settings()
