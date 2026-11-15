from pymongo.errors import PyMongoError

from flask import current_app, request


def require_dashboard_auth():
    """Fail closed before any dashboard data is fetched."""
    headers = {'Cache-Control': 'no-store'}
    # A normal initial browser challenge is not a password attempt.
    if not request.headers.get('Authorization'):
        headers['WWW-Authenticate'] = 'Basic realm="AWS Monitor", charset="UTF-8"'
        return 'Authentication required.', 401, headers
    throttle = current_app.extensions['auth_throttle']
    try:
        token, retry_after = throttle.reserve(
            request.remote_addr or 'unknown', current_app.config['AUTH_MAX_FAILURES'],
            current_app.config['AUTH_WINDOW_SECONDS'],
        )
    except (PyMongoError, ValueError):
        return 'Authentication temporarily unavailable.', 503, headers
    if token is None:
        headers['Retry-After'] = str(retry_after)
        return 'Too many login attempts. Please retry later.', 429, headers
    credentials = request.authorization
    valid = False
    if credentials and credentials.type == 'basic':
        try:
            valid = current_app.extensions['users'].authenticate(
                credentials.username or '', credentials.password or '',
            )
        except (PyMongoError, ValueError):
            return 'Authentication temporarily unavailable.', 503, headers
    if not valid:
        headers['WWW-Authenticate'] = 'Basic realm="AWS Monitor", charset="UTF-8"'
        return 'Authentication required.', 401, headers
    try:
        throttle.release(token)
    except (PyMongoError, ValueError):
        return 'Authentication temporarily unavailable.', 503, headers
