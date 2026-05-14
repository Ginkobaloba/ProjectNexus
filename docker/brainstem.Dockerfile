# docker/brainstem.Dockerfile
FROM python:3.11-slim

WORKDIR /app

# System deps (kept minimal; most wheels are prebuilt)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# CPU-only torch FIRST. The brainstem runs embeddings on CPU (see
# config.py: device default "cpu"), so there is no reason to pull the
# multi-GB CUDA torch wheel that sentence-transformers would otherwise
# drag in. The CPU wheel is a fraction of the size and turns a 20+ minute
# build into a couple of minutes. sentence-transformers then sees torch
# already satisfied and skips it.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# Remaining dependencies. Kept in its own layer, before the source COPY,
# so editing brainstem code does not invalidate the dependency layers.
RUN pip install --no-cache-dir \
    fastapi \
    "uvicorn[standard]" \
    sentence-transformers \
    pydantic \
    pydantic-settings \
    requests

# Copy code last so source changes only rebuild from here down.
COPY core /app/core
COPY bench /app/bench
COPY nodes/brainstem_4070 /app/brainstem_4070

# Add /app to Python import path
ENV PYTHONPATH="/app"

# Expose brainstem port
EXPOSE 5001

CMD ["uvicorn", "brainstem_4070.server:app", "--host", "0.0.0.0", "--port", "5001"]
