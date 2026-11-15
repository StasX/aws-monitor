"""Opt-in tests against a disposable MongoDB instance, never the production DB."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import os
import unittest
from uuid import uuid4

from pymongo import MongoClient

from app.utils.auth_throttle import AuthThrottle
from app.utils.mongodb import MongoDB
from app.logic.users_logic import UsersLogic
from app.repositories.user_repository import UserRepository
from pymongo.errors import DuplicateKeyError


@unittest.skipUnless(os.environ.get('MONGODB_TEST_URI'), 'Set MONGODB_TEST_URI for live MongoDB tests')
class MongoThrottleIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.uri = os.environ['MONGODB_TEST_URI']
        self.database = 'aws_monitor_test_' + uuid4().hex
        self.admin = MongoClient(self.uri, serverSelectionTimeoutMS=3000, tz_aware=True)
        self.addCleanup(self.admin.close)
        self.addCleanup(self.admin.drop_database, self.database)
        self.workers = [AuthThrottle(self.uri, self.database) for _ in range(2)]
        for worker in self.workers:
            self.addCleanup(lambda item=worker: item.client.close() if item.client is not None else None)

    def test_concurrent_replicas_share_one_budget(self):
        with ThreadPoolExecutor(max_workers=10) as pool:
            results = list(pool.map(lambda index: self.workers[index % 2].reserve('source', 5, 60), range(30)))
        self.assertEqual(sum(token is not None for token, _ in results), 5)
        collection = self.admin[self.database]['auth_attempts']
        document = collection.find_one()
        self.assertEqual(document['count'], 5)
        self.assertEqual(collection.count_documents({}), 1)
        self.assertNotIn('source', str(document))
        self.assertEqual(collection.index_information()['expiresAt_1']['expireAfterSeconds'], 0)

    def test_expiry_recovers_without_waiting_for_ttl_cleanup(self):
        worker = self.workers[0]
        old_token, _ = worker.reserve('source', 1, 60)
        self.assertIsNone(self.workers[1].reserve('source', 1, 60)[0])
        self.admin[self.database]['auth_attempts'].update_one(
            {'_id': old_token[0]}, {'$set': {'expiresAt': datetime.now(timezone.utc) - timedelta(seconds=1)}},
        )
        new_token, _ = self.workers[1].reserve('source', 1, 60)
        self.assertIsNotNone(new_token)
        worker.release(old_token)
        self.assertIsNone(worker.reserve('source', 1, 60)[0])

    def test_success_refund_does_not_erase_an_earlier_failure(self):
        worker = self.workers[0]
        worker.reserve('source', 2, 60)  # An earlier failed password check.
        token, _ = self.workers[1].reserve('source', 2, 60)
        self.workers[1].release(token)  # A later successful request.
        self.assertIsNotNone(worker.reserve('source', 2, 60)[0])
        self.assertIsNone(worker.reserve('source', 2, 60)[0])

    def test_user_lifecycle_is_shared_across_replicas(self):
        stores = [MongoDB(self.uri, self.database) for _ in range(2)]
        for store in stores:
            self.addCleanup(lambda item=store: item.client.close() if item.client is not None else None)
        users = [UsersLogic(UserRepository(store)) for store in stores]
        users[0].create('operator', 'correct horse battery staple')
        self.assertTrue(users[1].authenticate('operator', 'correct horse battery staple'))
        self.assertFalse(users[1].authenticate('operator', 'incorrect password'))
        with self.assertRaises(DuplicateKeyError):
            users[1].create('operator', 'a different password here')
        self.assertTrue(users[0].set_password('operator', 'replacement password here'))
        self.assertFalse(users[1].authenticate('operator', 'correct horse battery staple'))
        self.assertTrue(users[1].authenticate('operator', 'replacement password here'))
        self.assertTrue(users[0].set_active('operator', False))
        self.assertFalse(users[1].authenticate('operator', 'replacement password here'))
        self.assertTrue(users[0].set_active('operator', True))
        self.assertTrue(users[1].authenticate('operator', 'replacement password here'))
