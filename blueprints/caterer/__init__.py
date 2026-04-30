from flask import Blueprint

from blueprints.caterer.dashboard import register as _register_dashboard
from blueprints.caterer.profile import register as _register_profile
from blueprints.caterer.requests import register as _register_requests
from blueprints.caterer.orders import register as _register_orders
from blueprints.caterer.stripe_routes import register as _register_stripe
from blueprints.caterer.messages import register as _register_messages

caterer_bp = Blueprint("caterer", __name__, url_prefix="/caterer")

_register_dashboard(caterer_bp)
_register_profile(caterer_bp)
_register_requests(caterer_bp)
_register_orders(caterer_bp)
_register_stripe(caterer_bp)
_register_messages(caterer_bp)
