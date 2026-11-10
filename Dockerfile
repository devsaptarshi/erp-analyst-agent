# Builds the FastAPI backend (src/erp_analyst/api/). The frontend is a
# separate image (frontend/Dockerfile) — kept apart so either can be
# redeployed without rebuilding the other.
FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY scripts ./scripts
RUN uv sync --frozen --no-dev

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "erp_analyst.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
