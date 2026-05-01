from flask import Blueprint

from blueprints.client.dashboard import register as _register_dashboard
from blueprints.client.requests import register as _register_requests
from blueprints.client.orders import register as _register_orders
from blueprints.client.team import register as _register_team
from blueprints.client.messages import register as _register_messages
from blueprints.client.notifications import register as _register_notifications
from blueprints.client.profile import register as _register_profile

client_bp = Blueprint("client", __name__, url_prefix="/client")

_register_dashboard(client_bp)
_register_requests(client_bp)
_register_orders(client_bp)
_register_team(client_bp)
_register_messages(client_bp)
_register_notifications(client_bp)
_register_profile(client_bp)
