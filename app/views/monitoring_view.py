from flask import Blueprint, Response, current_app
from prometheus_client import CONTENT_TYPE_LATEST

monitoring_blueprint = Blueprint('monitoring_view', __name__)


@monitoring_blueprint.route('/health')
def health():
    return {'status': 'ok'}, 200


@monitoring_blueprint.route('/metrics')
def metrics():
    return Response(
        current_app.extensions['request_metrics'].render(),
        content_type=CONTENT_TYPE_LATEST,
        headers={'Cache-Control': 'no-store'},
    )
