from flask import Blueprint

monitoring_blueprint = Blueprint('monitoring_view', __name__)


@monitoring_blueprint.route('/health')
def health():
    return {'status': 'ok'}, 200


@monitoring_blueprint.route('/metrics')
def metrics():
    return '', 200
