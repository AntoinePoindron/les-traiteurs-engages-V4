web: gunicorn --bind 0.0.0.0:$PORT "app:create_app()"
worker: dramatiq services.billing_tasks --processes 1 --threads 4
postdeploy: alembic upgrade head && python init_db.py
