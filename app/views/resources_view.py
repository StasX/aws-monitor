from flask import Blueprint, render_template

from ..facades.resources_facade import ResourcesFacade
from ..utils.auth import require_dashboard_auth

resources_blueprint = Blueprint('resources_view', __name__)
resources_blueprint.before_request(require_dashboard_auth)


@resources_blueprint.after_request
def prevent_dashboard_caching(response):
    response.headers['Cache-Control'] = 'no-store'
    response.vary.add('Authorization')
    return response


@resources_blueprint.route('/')
def home():
    facade = ResourcesFacade()
    return render_template('index.html', **facade.get_resources())
