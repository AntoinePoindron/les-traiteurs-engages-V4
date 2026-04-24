"""Singleton instances of Flask extensions, importable from blueprints
without creating circular imports with app.py.
"""
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect

csrf = CSRFProtect()

# In-memory storage is fine for dev and single-worker prod.
# For multi-worker / multi-instance prod, switch to Redis via
# storage_uri="redis://..." — keys stay consistent across workers.
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["1000 per hour"],  # global sanity cap
    storage_uri="memory://",
)
