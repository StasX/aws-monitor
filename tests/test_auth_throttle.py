from datetime import datetime, timedelta, timezone
from hashlib import sha256
import unittest
from unittest.mock import Mock, patch

from pymongo.errors import ConfigurationError, DuplicateKeyError, PyMongoError

from app import create_app
from app.utils.auth_throttle import AuthThrottle


class AuthThrottleTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.update(TESTING=True, AUTH_MAX_FAILURES=2,
                               AUTH_WINDOW_SECONDS=60)
        self.throttle = Mock()
        self.throttle.reserve.return_value = (('source', 'window'), 0)
        self.app.extensions['auth_throttle'] = self.throttle
        self.users = Mock()
        self.users.authenticate.return_value = False
        self.app.extensions['users'] = self.users
        self.client = self.app.test_client()

    def attempt(self, password='wrong', **kwargs):
        return self.client.get('/', auth=('operator', password), **kwargs)

    def test_blocked_request_skips_password_hash_and_aws(self):
        self.throttle.reserve.return_value = (None, 42)
        with patch.object(self.users, 'authenticate') as verify, \
                patch.object(self.app.extensions['resources_cache'], 'get_resources') as aws:
            response = self.attempt()
            self.assertEqual(response.status_code, 429)
            self.assertEqual(response.headers['Retry-After'], '42')
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            verify.assert_not_called()
            aws.assert_not_called()
        for route in ['/health', '/metrics']:
            self.assertEqual(self.client.get(route).status_code, 200)

    def test_source_ignores_forged_forwarding_headers_and_username(self):
        with patch.object(self.users, 'authenticate', return_value=False):
            self.attempt(headers={'X-Forwarded-For': '203.0.113.5'})
            self.throttle.reserve.assert_called_with('127.0.0.1', 2, 60)
            self.client.get('/', auth=('other', 'wrong'))
            self.throttle.reserve.assert_called_with('127.0.0.1', 2, 60)

    def test_success_refunds_slot_but_failure_does_not(self):
        with patch.object(self.users, 'authenticate', return_value=False):
            self.assertEqual(self.attempt().status_code, 401)
        self.throttle.release.assert_not_called()
        with patch.object(self.users, 'authenticate', return_value=True), \
                patch('app.views.resources_view.render_template', return_value='dashboard'), \
                patch.object(self.app.extensions['resources_cache'], 'get_resources', return_value=({'freshness': {}}, {})):
            self.assertEqual(self.attempt('correct').status_code, 200)
        self.throttle.release.assert_called_once_with(('source', 'window'))

    def test_initial_browser_challenge_does_not_consume_slot(self):
        self.assertEqual(self.client.get('/').status_code, 401)
        self.throttle.reserve.assert_not_called()

    def test_malformed_authorization_consumes_slot(self):
        self.assertEqual(self.client.get('/', headers={'Authorization': 'Basic !!!'}).status_code, 401)
        self.throttle.reserve.assert_called_once()
        self.throttle.release.assert_not_called()

    def test_storage_errors_fail_closed_without_details(self):
        for method in ['reserve', 'release']:
            with self.subTest(method=method), \
                    patch.object(self.throttle, method, side_effect=PyMongoError('sensitive URI')), \
                    patch.object(self.users, 'authenticate', return_value=True):
                response = self.attempt()
                self.assertEqual(response.status_code, 503)
                self.assertNotIn('sensitive', response.get_data(as_text=True))


class MongoThrottleUnitTests(unittest.TestCase):
    def setUp(self):
        self.throttle = AuthThrottle('mongodb://unused', 'test_database')
        self.collection = Mock()
        self.throttle.collection = self.collection
        self.now = datetime(2026, 11, 15, tzinfo=timezone.utc)
        self.key = sha256(b'client').hexdigest()

    def test_allowed_reservation_uses_returned_window(self):
        expires = self.now + timedelta(seconds=60)
        self.collection.find_one_and_update.return_value = {
            'allowed': True, 'expiresAt': expires, 'observedAt': self.now,
        }
        token, retry_after = self.throttle.reserve('client', 5, 60)
        self.assertEqual(token, (self.key, expires))
        self.assertEqual(retry_after, 0)
        self.assertEqual(self.collection.find_one_and_update.call_args.args[0], {'_id': self.key})

    def test_retry_after_uses_database_clock_and_rounds_up(self):
        self.collection.find_one_and_update.return_value = {
            'allowed': False, 'expiresAt': self.now + timedelta(seconds=1.2), 'observedAt': self.now,
        }
        self.assertEqual(self.throttle.reserve('client', 5, 60), (None, 2))

    def test_first_insert_race_retries_without_losing_limit(self):
        self.collection.find_one_and_update.side_effect = [DuplicateKeyError('race'), {
            'allowed': False, 'expiresAt': self.now + timedelta(seconds=60), 'observedAt': self.now,
        }]
        self.assertEqual(self.throttle.reserve('client', 5, 60), (None, 60))
        self.assertEqual(self.collection.find_one_and_update.call_count, 2)

    def test_no_uri_fails_closed_instead_of_local_fallback(self):
        with self.assertRaises(ConfigurationError):
            AuthThrottle().reserve('client', 5, 60)

    def test_client_and_ttl_index_are_initialized_once(self):
        throttle = AuthThrottle('mongodb://unused', 'test_database')
        with patch('app.utils.mongodb.MongoClient') as factory:
            first = throttle._collection()
            self.assertIs(first, throttle._collection())
            factory.assert_called_once()
            first.create_index.assert_called_once_with('expiresAt', expireAfterSeconds=0)

    def test_release_matches_original_window(self):
        self.throttle.release((self.key, self.now))
        self.collection.update_one.assert_called_once_with(
            {'_id': self.key, 'expiresAt': self.now, 'count': {'$gt': 0}}, {'$inc': {'count': -1}},
        )
