# --- Frontend build ---
FROM node:20-alpine AS frontend-build
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- Python dependencies build ---
FROM python:3.12-slim AS py-build
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    default-libmysqlclient-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --prefix=/install --no-cache-dir -r requirements.txt

# --- Runtime ---
FROM python:3.12-slim AS runtime
WORKDIR /app
RUN addgroup --system app && adduser --system --ingroup app --uid 1000 app
COPY --from=py-build /install /usr/local
COPY app ./app
COPY openapi ./openapi
COPY --from=frontend-build /fe/dist ./frontend/dist

ENV PYTHONUNBUFFERED=1
EXPOSE 8000
USER app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
