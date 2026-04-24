"""Singleton instances of Flask extensions, importable from blueprints
without creating circular imports with app.py.
"""
from flask_wtf.csrf import CSRFProtect

csrf = CSRFProtect()
