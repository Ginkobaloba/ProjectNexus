# docker/brainstem.Dockerfile
FROM python:3.11-slim

WORKDIR /app

# System deps (kept minimal; all wheels are prebuilt).
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Sprint 2 Chunk A: brainstem no longer owns the embedding model. The
# embedder service in its own container does. That drops torch and
# sentence-transformers from this image entirely, which shrinks the
# image and the rebuild time substantially.
RUN pip install --no-cache-dir \
    fastapi \
    "uvicorn[standard]" \
    pydantic \
    pydantic-settings \
    requests

# Copy code last so source changes only rebuild from here down.
COPY core /app/core
COPY bench /app/bench
COPY nodes/brainstem_4070 /app/brainstem_4070

ENV PYTHONPATH="/app"

EXPOSE 5001

CMD ["uvicorn", "brainstem_4070.server:app", "--host", "0.0.0.0", "--port", "5001"]
