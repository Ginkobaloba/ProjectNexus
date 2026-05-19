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

    # --Embedder-- separate container that owns the embedding model and
    # the Chroma `memory` collection. Brainstem talks to it over the
    # compose network for write-on-turn and retrieve-before-generate.
    embedder_url: str = "http://embedder_4070:5003"
    embedder_timeout: float = 30.0

    # --Cortex-- 4090 heavy-inference peer (vLLM, OpenAI-compatible API).
    # LAN address of DREWSPC. Override with BRAINSTEM_CORTEX_URL if needed.
    cortex_url: str = "http://192.168.1.140:8000"
    # Per-request timeout (seconds) for generation calls to Cortex.
    cortex_timeout: float = 120.0
    # Short timeout for reachability / model-list checks (the dashboard's
    # /fabric/status poll uses this, so it must stay snappy even if the
    # 4090 is slow or down).
    cortex_health_timeout: float = 5.0

    # --Metrics harness-- Phase 0 Component G.
    # JSONL sink for per-request metric records (the persistent data
    # layer). The live dashboard reads an in-process ring buffer of the
    # last `metrics_window` records rather than re-reading the file.
    metrics_path: str = "/data/metrics/brainstem_metrics.jsonl"
    metrics_window: int = 200

    # --Auth-- Sprint 3b token store.
    # JSON file with hashed bearer tokens (one per client). Lives on the
    # `auth_data` docker named volume so it survives container restarts.
    # See docs/auth_middleware.md for the schema and the decision log.
    token_store_path: str = "/data/auth/tokens.json"

    # --Cortex-down handling-- Sprint 3c.
    # Structured 503 returned by /generate when the 4090 Cortex peer is
    # unreachable. The body carries `retry_after_seconds`; the Retry-After
    # response header carries the same integer. Two knobs because a hard
    # "connection refused" is a different operational signal than a
    # timeout (model loaded but slow). See docs/exposure_and_cortex_down.md.
    cortex_down_retry_after_seconds: int = 5
    cortex_timeout_retry_after_seconds: int = 15

    # Service
    # Inside the container the brainstem listens on 0.0.0.0 so compose-
    # network peers (embedder, nas) can reach it and the healthcheck can
    # hit it from the same container. The HOST-side bind is restricted to
    # the Tailscale interface via docker-compose port mapping (the env var
    # BRAINSTEM_BIND_HOST in docker/.env). See docs/exposure_and_cortex_down.md.
    host: str = "0.0.0.0"
    port: int = 5001

    log_level: str = "INFO"

    class Config:
        env_prefix = "BRAINSTEM_"
        case_sensitive = False


settings = Settings()
