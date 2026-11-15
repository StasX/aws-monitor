from flask import Blueprint, render_template

from ..facades.resources_facade import ResourcesFacade

resources_blueprint = Blueprint('resources_view', __name__)


@resources_blueprint.route('/')
def home():
    facade = ResourcesFacade()
    return render_template('index.html', **facade.get_resources())
