# Backend service

Minimal Python backend for SysWatch.

Run locally:

```bash
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

API:

- `GET /health` — returns status
- `GET /snapshot` — proxy to C++ Agent (implemented in later commits)
