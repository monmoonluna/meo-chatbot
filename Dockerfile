FROM python:3.13-slim

# build tools for any non-wheel deps (lxml/trafilatura etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential git && rm -rf /var/lib/apt/lists/*

# HF Spaces convention: run as non-root uid 1000
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    HF_HOME=/home/user/app/hf-cache

WORKDIR /home/user/app

RUN pip install --user --no-cache-dir uv

# copy code, install runtime deps only (skip the dev/pytest group)
COPY --chown=user . .
RUN uv sync --no-dev

# pull prebuilt ChromaDB + chunks (~1 GB) from your HF dataset into data/
RUN uv run python scripts/download_data.py --repo-id Monmoonluna/meo-chatbot-data

# (optional) pre-cache e5 + reranker into the image → fast cold start
RUN uv run python -c "from app.retriever import warmup; warmup()"

EXPOSE 7860
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]