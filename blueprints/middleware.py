from functools import wraps

from flask import abort, flash, g, redirect, url_for


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not g.get("current_user"):
            flash("Veuillez vous connecter pour acceder a cette page.", "error")
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated


def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not g.get("current_user"):
                flash("Veuillez vous connecter pour acceder a cette page.", "error")
                return redirect(url_for("auth.login"))
            if g.current_user.role not in roles:
                abort(403)
            return f(*args, **kwargs)
        return decorated
    return decorator


