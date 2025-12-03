# NAS Dockerfile
FROM python:3.11-slim

# Set working dir inside container
WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy ONLY nas-memory folder
COPY ./nodes/nas_memory /app/nas_memory

# Install NAS dependencies
RUN pip install --no-cache-dir \
    fastapi \
    "uvicorn[standard]" \
    chromadb \
    pydantic \
    pydantic-settings

# Expose NAS port
EXPOSE 5002

# Start the NAS API
CMD ["uvicorn", "nas_memory.server:app", "--host", "0.0.0.0", "--port", "5002"]


