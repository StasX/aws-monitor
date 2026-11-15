import unittest
from unittest.mock import patch

from werkzeug.security import generate_password_hash

from app import create_app


class DashboardAuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password_hash = generate_password_hash('test-password')

    def setUp(self):
        self.app = create_app()
        self.app.config.update(
            TESTING=True, DASHBOARD_USERNAME='operator',
            DASHBOARD_PASSWORD_HASH=self.password_hash,
        )
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

    def test_missing_or_invalid_configuration_blocks_access(self):
        for settings, status in [
            ({'DASHBOARD_USERNAME': ''}, 503),
            ({'DASHBOARD_PASSWORD_HASH': ''}, 503),
            ({'DASHBOARD_PASSWORD_HASH': 'invalid'}, 401),
        ]:
            with self.subTest(settings=settings), patch.dict(self.app.config, settings):
                self.assertEqual(self.client.get('/', auth=('operator', 'test-password')).status_code, status)
        self.resources.assert_not_called()

    def test_monitoring_remains_public_without_credentials(self):
        self.app.config.update(DASHBOARD_USERNAME='', DASHBOARD_PASSWORD_HASH='')
        for route in ['/health', '/metrics']:
            self.assertEqual(self.client.get(route).status_code, 200)
        self.resources.assert_not_called()
