# fiscal-agent (backend)

Backend Python del chatbot — agente fiscal vertical para calendarios de vencimientos ARCA.
Migrado desde `backend/Backend a migrar/` (paquete `fiscal_agent`) como parte del plan
documentado en [`BACKEND-MIGRATION.md`](../BACKEND-MIGRATION.md).

Consumido por el frontend Next.js en [`frontend/`](../frontend/).

## Stack

- FastAPI + Pydantic v2 + uvicorn
- Redis (cache, rate limit, colas)
- ReportLab (PDFs), Composio (browser automation), Engram (memoria por CUIT)
- Typer CLI

## Instalación

Con [uv](https://docs.astral.sh/uv/) (recomendado):

```bash
cd backend
uv sync --dev
```

Sin uv (venv + pip):

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Copiá `backend/.env.example` a `backend/.env` y completá las variables.

## Correr la API

```bash
uv run uvicorn fiscal_agent.api.server:app --reload
```

Health check: `http://localhost:8000/health`

## CLI

```bash
uv run python -m fiscal_agent --help
uv run python -m fiscal_agent run --config clients.yaml
```

## Tests

```bash
uv run pytest
```

Los tests que dependen de servicios externos (Redis real, Engram, Composio) usan
`fakeredis`/mocks o se saltan si el servicio no está disponible.

## Docker

```bash
cd backend
docker build -t fiscal-agent .
docker run -p 8000:8000 --env-file .env fiscal-agent
```

## Enlaces

- Plan de migración: [`BACKEND-MIGRATION.md`](../BACKEND-MIGRATION.md)
- Frontend: [`frontend/`](../frontend/)
