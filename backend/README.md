# Backend service

Minimal Python backend for SysWatch.

## Run locally

```bash
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

## API

- `GET /health` — returns the service health status
- `GET /snapshot` — fetches a snapshot from the C++ Agent and returns it as a typed model

## Structure

- `app/api` — FastAPI routes
- `app/client` — HTTP client for the C++ Agent
- `app/models` — Pydantic snapshot models
- `app/services` — service layer for snapshot handling
- `tests` — endpoint and service tests
