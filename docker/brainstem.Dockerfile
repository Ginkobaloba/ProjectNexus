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
    requests \
    argon2-cffi \
    pyyaml

# Copy code last so source changes only rebuild from here down.
COPY core /app/core
COPY bench /app/bench
COPY nodes/brainstem_4070 /app/brainstem_4070
# Sprint 3b: token CLI runs from inside the container so the plaintext
# token never crosses the network. `docker compose exec brainstem
# python scripts/create_token.py --name <client>`.
COPY scripts /app/scripts
# Sprint 5 Card 1: family registry + member spec files (V2 doc Section
# 4.1). server.py computes REPO_ROOT as parents[2] of its own file,
# which assumes the on-checkout layout `<root>/nodes/brainstem_4070/
# server.py`. In this image the `nodes/` prefix is dropped (source
# lands at /app/brainstem_4070), so that walk would land on `/` instead
# of `/app`. Rather than reshuffle the image layout to mirror the repo
# tree, we copy family/ to a known absolute path and point
# BRAINSTEM_FAMILY_REGISTRY_PATH (see docker-compose.yml) at it
# directly, which short-circuits the REPO_ROOT walk entirely.
COPY family /app/family

ENV PYTHONPATH="/app"

EXPOSE 5001

CMD ["uvicorn", "brainstem_4070.server:app", "--host", "0.0.0.0", "--port", "5001"]
