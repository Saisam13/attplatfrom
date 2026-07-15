@echo off
cd /d "%~dp0"
echo Starting DEV mode: uvicorn --reload on :8000 + vite dev server on :5173
start "ATT backend" cmd /k "venv\Scripts\python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000"
cd frontend
start "ATT frontend" cmd /k "npm run dev"
echo Open http://localhost:5173 (API proxied to :8000)
