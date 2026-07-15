# Dockerfile stub — not required for LAN deployment (use start.bat).
# Migration notes in README.md.
FROM node:24-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./backend/
COPY config.json ./
COPY data/default_base_portfolio.xlsx ./data/default_base_portfolio.xlsx
COPY --from=frontend /app/frontend/dist ./frontend/dist
VOLUME /app/data
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
