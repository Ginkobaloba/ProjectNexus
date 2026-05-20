# NAS Dockerfile
FROM python:3.11-slim

# Set working dir inside container
WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install NAS dependencies before the source COPY so editing nas_memory
# code does not invalidate the (slow) dependency layer.
RUN pip install --no-cache-dir \
    fastapi \
    "uvicorn[standard]" \
    chromadb \
    pydantic \
    pydantic-settings

# Copy ONLY the nas_memory package
COPY ./nodes/nas_memory /app/nas_memory

# NAS imports as the package `nas_memory`; /app is the import root.
ENV PYTHONPATH="/app"

# Expose NAS port
EXPOSE 5002

# Start the NAS API
CMD ["uvicorn", "nas_memory.server:app", "--host", "0.0.0.0", "--port", "5002"]
