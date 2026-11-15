from datetime import datetime, timezone
import unittest
from unittest.mock import Mock

from app.models.user import User
from app.repositories.user_repository import UserRepository


class UserModelTests(unittest.TestCase):
    def test_document_round_trip_preserves_fields(self):
        now = datetime.now(timezone.utc)
        document = {'_id': 'operator', 'password_hash': 'stored-hash', 'active': True,
                    'created_at': now, 'updated_at': now}
        user = User.from_document(document)
        self.assertEqual(user.username, 'operator')
        self.assertEqual(user.to_document(), document)

    def test_repr_does_not_expose_password_hash(self):
        user = User('operator', 'sensitive-hash')
        self.assertNotIn('sensitive-hash', repr(user))

    def test_invalid_persisted_accounts_are_rejected_or_disabled(self):
        base = {'_id': 'operator', 'password_hash': 'stored-hash', 'active': True}
        for overrides in [{'_id': None}, {'password_hash': None}, {'password_hash': ''},
                          {'active': 1}, {'active': 'true'}]:
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                User.from_document({**base, **overrides})
        self.assertFalse(User.from_document({'_id': 'operator', 'password_hash': 'stored-hash'}).active)

    def test_existing_documents_without_timestamps_remain_usable(self):
        user = User.from_document({'_id': 'operator', 'password_hash': 'stored-hash', 'active': True})
        self.assertTrue(user.active)
        self.assertIsNone(user.created_at)

    def test_repository_returns_model_or_none(self):
        store = Mock()
        collection = store.get_collection.return_value
        repository = UserRepository(store)
        collection.find_one.return_value = {'_id': 'operator', 'password_hash': 'stored-hash', 'active': True}
        self.assertIsInstance(repository.find_by_username('operator'), User)
        collection.find_one.assert_called_with({'_id': 'operator'})
        collection.find_one.return_value = None
        self.assertIsNone(repository.find_by_username('missing'))
