#!/usr/bin/env bash
set -e

echo "Running schema initialization..."
psql "$DATABASE_URL" -f scripts/init_db.sql

echo "Starting uvicorn on port ${PORT:-8000}..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
