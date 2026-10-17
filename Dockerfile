# Multi-stage Dockerfile: Builds React frontend and serves unified app via FastAPI + Uvicorn
FROM node:20-slim AS frontend-builder
WORKDIR /app/frontend

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# Python backend runtime
FROM python:3.12-slim

WORKDIR /app

# Install system dependencies (SQLite3, git, curl)
RUN apt-get update && apt-get install -y --no-install-recommends \
    sqlite3 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r ./backend/requirements.txt

# Copy backend application code
COPY backend ./backend

# Copy built frontend from frontend-builder stage into frontend/dist
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

WORKDIR /app/backend

# Default port for Cloud Run / Render is 8080 or PORT env var
ENV PORT=8080
ENV HOST=0.0.0.0
ENV PYTHONPATH=/app/backend

EXPOSE 8080

CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
