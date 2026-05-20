# nodes/embedder_4070/config.py
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # --- Model ---------------------------------------------------------
    # BGE-small chosen for write-on-turn latency. 384-dim, ~133MB, 512
    # max sequence. Swap target without touching the API: this is a
    # service boundary.
    model_name: str = "BAAI/bge-small-en-v1.5"
    device: str = "cpu"  # 4070 box; CPU is fine at single-user rates

    # --- Chunking ------------------------------------------------------
    # Token-aware against the model's own tokenizer (so the count matches
    # what the encoder will actually see).
    chunk_threshold_tokens: int = 450   # below this, do not chunk
    chunk_target_tokens: int = 400      # target size when we do chunk
    chunk_overlap_tokens: int = 50      # cross-chunk context for retrieval

    # --- Chroma --------------------------------------------------------
    chroma_persist_dir: str = "/chroma"
    chroma_collection: str = "memory"

    # --- Service -------------------------------------------------------
    host: str = "0.0.0.0"
    port: int = 5003
    log_level: str = "INFO"

    class Config:
        env_prefix = "EMBEDDER_"
        case_sensitive = False


settings = Settings()
