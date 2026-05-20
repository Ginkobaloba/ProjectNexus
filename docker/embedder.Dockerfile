# docker/embedder.Dockerfile
#
# Embedder service. Lives on the 4070 box, separate container from the
# brainstem. Owns the sentence-transformer model and the Chroma store.
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# CPU torch first, same reasoning as the brainstem Dockerfile: a fraction
# of the size of the CUDA wheel and sentence-transformers will see torch
# already satisfied. The embedder is single-user CPU at Phase 0.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# Service deps. Chroma is the heavyweight here; everything else is small.
RUN pip install --no-cache-dir \
    fastapi \
    "uvicorn[standard]" \
    sentence-transformers \
    chromadb \
    pydantic \
    pydantic-settings

# Source last so code changes do not invalidate the dep layers.
COPY nodes/embedder_4070 /app/embedder_4070

ENV PYTHONPATH="/app"

EXPOSE 5003

CMD ["uvicorn", "embedder_4070.server:app", "--host", "0.0.0.0", "--port", "5003"]
