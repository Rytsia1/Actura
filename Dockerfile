# Stage 1: Builder
FROM python:3.11-slim as builder

WORKDIR /app

# Install system dependencies required for compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Ensure modern build toolchain
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

COPY requirements.txt .

# Create python wheels for all dependencies (including all transitive dependencies)
RUN pip wheel --no-cache-dir --wheel-dir /app/wheels -r requirements.txt


# Stage 2: Runtime
FROM python:3.11-slim

WORKDIR /app

# Install runtime dependencies (e.g., libpq for psycopg2)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user and group
RUN groupadd -r actura && useradd -r -g actura actura

# Copy requirements and wheels from builder and install them deterministically
COPY requirements.txt .
COPY --from=builder /app/wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels

# Copy application code
COPY --chown=actura:actura . .

# Switch to non-root user
USER actura

# Set explicit environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/app

EXPOSE 8000

CMD ["uvicorn", "actuary_engine.main:app", "--host", "0.0.0.0", "--port", "8000"]
