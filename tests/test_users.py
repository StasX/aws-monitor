import unittest
from unittest.mock import Mock, patch

from pymongo.errors import DuplicateKeyError, PyMongoError
from werkzeug.security import check_password_hash

from app import create_app
from app.logic.users_logic import UsersLogic
from app.repositories.user_repository import UserRepository


class UserStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = Mock()
        self.collection = self.store.get_collection.return_value
        self.users = UsersLogic(UserRepository(self.store))

    def test_creation_stores_salted_hash_not_plaintext(self):
        password = 'correct horse battery staple'
        self.users.create('operator', password)
        document = self.collection.insert_one.call_args.args[0]
        self.assertEqual(document['_id'], 'operator')
        self.assertTrue(document['active'])
        self.assertTrue(document['password_hash'].startswith('scrypt:'))
        self.assertTrue(check_password_hash(document['password_hash'], password))
        self.assertNotIn(password, str(document))
        self.store.get_collection.assert_called_with('users')

    def test_invalid_input_is_rejected_before_database_access(self):
        for username in ['', ' operator', 'operator ', 'a:b', 'a\nb', 'a' * 129]:
            with self.subTest(username=username), self.assertRaises(ValueError):
                self.users.create(username, 'correct horse battery staple')
        for password in ['', 'short-password', 'a' * 1025]:
            with self.subTest(length=len(password)), self.assertRaises(ValueError):
                self.users.create('operator', password)
        self.store.get_collection.assert_not_called()

    def test_unknown_user_still_checks_dummy_hash(self):
        self.collection.find_one.return_value = None
        with patch('app.logic.users_logic.check_password_hash', return_value=True) as verify:
            self.assertFalse(self.users.authenticate('unknown', 'password'))
        verify.assert_called_once()

    def test_duplicate_user_is_not_overwritten(self):
        self.collection.insert_one.side_effect = DuplicateKeyError('duplicate')
        with self.assertRaises(DuplicateKeyError):
            self.users.create('operator', 'correct horse battery staple')
        self.collection.update_one.assert_not_called()

    def test_password_reset_keeps_disabled_status(self):
        self.collection.update_one.return_value.matched_count = 1
        self.assertTrue(self.users.set_password('operator', 'correct horse battery staple'))
        query, update = self.collection.update_one.call_args.args
        self.assertEqual(query, {'_id': 'operator'})
        self.assertNotIn('active', update['$set'])
        self.assertTrue(check_password_hash(update['$set']['password_hash'], 'correct horse battery staple'))
        self.collection.update_one.return_value.matched_count = 0
        self.assertFalse(self.users.set_password('missing', 'correct horse battery staple'))

    def test_enable_disable_does_not_change_password(self):
        self.collection.update_one.return_value.matched_count = 1
        self.assertTrue(self.users.set_active('operator', False))
        update = self.collection.update_one.call_args.args[1]['$set']
        self.assertFalse(update['active'])
        self.assertNotIn('password_hash', update)


class UserCommandTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.users = Mock()
        self.app.extensions['users'] = self.users
        self.runner = self.app.test_cli_runner()

    def test_create_prompts_hides_and_confirms_password(self):
        password = 'correct horse battery staple'
        result = self.runner.invoke(args=['users', 'create', 'operator'], input=f'{password}\n{password}\n')
        self.assertEqual(result.exit_code, 0, result.output)
        self.users.create.assert_called_once_with('operator', password)
        self.assertNotIn(password, result.output)

    def test_mismatched_confirmation_does_not_create_user(self):
        result = self.runner.invoke(args=['users', 'create', 'operator'], input='first-password\nother-password\n')
        self.assertNotEqual(result.exit_code, 0)
        self.users.create.assert_not_called()

    def test_database_failure_does_not_expose_connection_string(self):
        self.users.create.side_effect = PyMongoError('mongodb://user:secret@server')
        result = self.runner.invoke(args=['users', 'create', 'operator'], input='password\npassword\n')
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn('MongoDB is unavailable', result.output)
        self.assertNotIn('secret', result.output)

    def test_duplicate_user_explains_password_reset_command(self):
        self.users.create.side_effect = DuplicateKeyError('duplicate')
        result = self.runner.invoke(args=['users', 'create', 'operator'], input='password\npassword\n')
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn('users set-password', result.output)

    def test_set_password_enable_and_disable_existing_user(self):
        result = self.runner.invoke(args=['users', 'set-password', 'operator'], input='new-password\nnew-password\n')
        self.assertEqual(result.exit_code, 0, result.output)
        self.users.set_password.assert_called_once_with('operator', 'new-password')
        for command, active in [('disable', False), ('enable', True)]:
            result = self.runner.invoke(args=['users', command, 'operator'])
            self.assertEqual(result.exit_code, 0, result.output)
            self.users.set_active.assert_called_with('operator', active)

    def test_nonexistent_account_is_not_silently_created(self):
        self.users.set_active.return_value = False
        result = self.runner.invoke(args=['users', 'disable', 'missing'])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn('User does not exist', result.output)
