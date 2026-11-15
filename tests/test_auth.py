import unittest
from unittest.mock import Mock, patch

from werkzeug.security import generate_password_hash
from pymongo.errors import PyMongoError

from app import create_app


class DashboardAuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password_hash = generate_password_hash('test-password')

    def setUp(self):
        self.app = create_app()
        self.app.extensions['auth_throttle'] = Mock()
        self.app.extensions['auth_throttle'].reserve.return_value = (('source', 'window'), 0)
        self.app.config.update(TESTING=True, AUTH_MAX_FAILURES=20)
        self.collection = Mock()
        self.collection.find_one.side_effect = lambda query: (
            {'_id': 'operator', 'password_hash': self.password_hash, 'active': True}
            if query['_id'] == 'operator' else None
        )
        self.app.extensions['users'].repository.store = Mock()
        self.app.extensions['users'].repository.store.get_collection.return_value = self.collection
        self.client = self.app.test_client()
        self.fetch = patch.object(self.app.extensions['resources_cache'], 'get_resources')
        self.resources = self.fetch.start()
        self.addCleanup(self.fetch.stop)

    def test_unauthorized_requests_never_fetch_resources(self):
        for headers in [{}, {'Authorization': 'Basic !!!'}, {'Authorization': 'Bearer token'}]:
            with self.subTest(headers=headers):
                response = self.client.get('/', headers=headers)
                self.assertEqual(response.status_code, 401)
                self.assertIn('Basic realm=', response.headers['WWW-Authenticate'])
                self.assertEqual(response.headers['Cache-Control'], 'no-store')
        for credentials in [('operator', 'wrong'), ('wrong', 'test-password'), ('operator', '')]:
            self.assertEqual(self.client.get('/', auth=credentials).status_code, 401)
        self.resources.assert_not_called()

    def test_valid_credentials_allow_dashboard_without_caching(self):
        with patch('app.views.resources_view.render_template', return_value='dashboard'):
            self.resources.return_value = ({'freshness': {}}, {})
            response = self.client.get('/', auth=('operator', 'test-password'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertIn('Authorization', response.headers['Vary'])
        self.resources.assert_called_once()

    def test_disabled_missing_or_invalid_users_cannot_login(self):
        for user in [None, {'active': False, 'password_hash': self.password_hash},
                     {'active': True, 'password_hash': 'invalid'}, {'active': True},
                     {'password_hash': self.password_hash}]:
            with self.subTest(user=user):
                self.collection.find_one.side_effect = None
                self.collection.find_one.return_value = user
                self.assertEqual(self.client.get('/', auth=('operator', 'test-password')).status_code, 401)
        self.resources.assert_not_called()

    def test_user_database_failure_returns_safe_error(self):
        self.collection.find_one.side_effect = PyMongoError('sensitive connection details')
        response = self.client.get('/', auth=('operator', 'test-password'))
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('sensitive', response.get_data(as_text=True))
        self.resources.assert_not_called()

    def test_monitoring_remains_public_without_credentials(self):
        for route in ['/health', '/metrics']:
            self.assertEqual(self.client.get(route).status_code, 200)
        self.resources.assert_not_called()
