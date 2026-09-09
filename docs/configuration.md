# Actura Configuration & Deployment

Actura is built for reproducibility and easy deployment across development, testing, and production environments.

## Environment Variables

Actura respects the following environment variables to control its execution environment:

- **`DATABASE_URL`**: Connection string to the SQL database.
  - *Default*: `sqlite:///jobs.db`
  - *Example (PostgreSQL)*: `postgresql://actura_user:actura_pass@db:5432/actura_db`
- **`PYTHONUNBUFFERED`**: Ensures Python standard out streams are flushed immediately, useful for Docker logs. Set to `1`.
- **`PYTHONDONTWRITEBYTECODE`**: Prevents Python from writing `.pyc` files to disk.

## Database Configurations

Actura uses SQLAlchemy Core to abstract its database layer.

### SQLite (Local Development)
By default, omitting the `DATABASE_URL` causes Actura to fall back to a local SQLite database named `jobs.db` located at the root of the project. This is lightweight and requires no external services.

### PostgreSQL (Production)
For production or staging environments with concurrent workloads, PostgreSQL is recommended. 
To configure PostgreSQL:
1. Ensure the PostgreSQL container is running (via `docker-compose.yml`).
2. Supply `DATABASE_URL=postgresql://user:password@host:port/db_name` to the backend container.

## Docker Container Architecture

Actura uses a **multi-stage Docker build** (`Dockerfile`):

1. **Builder Stage**: Installs C-level build dependencies (like `build-essential` and `libpq-dev`), and compiles wheels for the pinned dependencies in `requirements.txt`.
2. **Runtime Stage**: A slim Python image that only installs runtime dependencies (`libpq5`). It copies the precompiled wheels from the builder and installs them, resulting in a significantly smaller and safer final image.

### Non-Root Execution
For enhanced security, the Docker container does not run as `root`. It runs as the newly created `actura` user.

## Running with Docker Compose

Actura provides a `docker-compose.yml` pre-configured with profiles for local development and production.

### Development Mode (SQLite)
Run the application using the local SQLite database.
```bash
docker-compose --profile dev up --build
```

### Production Mode (PostgreSQL)
Run the application with the PostgreSQL database container.
```bash
docker-compose --profile prod up --build -d
```
