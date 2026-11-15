from hmac import compare_digest

from flask import current_app, request
from werkzeug.security import check_password_hash


def require_dashboard_auth():
    """Fail closed before any dashboard data is fetched."""
    username = current_app.config['DASHBOARD_USERNAME']
    password_hash = current_app.config['DASHBOARD_PASSWORD_HASH']
    headers = {'Cache-Control': 'no-store'}
    if not username or not password_hash:
        return 'Dashboard access is not configured.', 503, headers
    credentials = request.authorization
    valid = False
    if credentials and credentials.type == 'basic':
        try:
            password_valid = check_password_hash(password_hash, credentials.password or '')
            valid = compare_digest(
                (credentials.username or '').encode('utf-8'), username.encode('utf-8')
            ) and password_valid
        except (ValueError, TypeError):
            pass
    if not valid:
        headers['WWW-Authenticate'] = 'Basic realm="AWS Monitor", charset="UTF-8"'
        return 'Authentication required.', 401, headers
