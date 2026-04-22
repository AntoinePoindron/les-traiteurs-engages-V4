#!/bin/sh
set -e

echo "Initializing database..."
python init_db.py

echo "Seeding data..."
python seed_data.py || true

echo "Starting gunicorn..."
exec gunicorn --bind 0.0.0.0:8000 "app:create_app()"
