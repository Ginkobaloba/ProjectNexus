# docker/brainstem.Dockerfile
FROM python:3.11-slim

WORKDIR /app

# System deps if needed
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy only brainstem node code
COPY ./nodes/brainstem_4070 /app/brainstem_4070

# Install dependencies
RUN pip install --no-cache-dir \
    fastapi \
    "uvicorn[standard]" \
    sentence-transformers \
    pydantic \
    pydantic-settings

# Expose brainstem port
EXPOSE 5001

CMD ["uvicorn", "brainstem_4070.server:app", "--host", "0.0.0.0", "--port", "5001"]

