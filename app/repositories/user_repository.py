from datetime import datetime, timezone

from pymongo import timeout

from ..models.user import User


class UserRepository:
    """Persist User models without depending on Flask or authentication rules."""

    def __init__(self, store):
        self.store = store

    def find_by_username(self, username):
        with timeout(3):
            document = self.store.get_collection('users').find_one({'_id': username})
        return User.from_document(document) if document is not None else None

    def insert(self, user: User):
        with timeout(3):
            # MongoDB's _id uniqueness prevents concurrent duplicate accounts.
            self.store.get_collection('users').insert_one(user.to_document())

    def set_password(self, username, password_hash):
        with timeout(3):
            result = self.store.get_collection('users').update_one(
                {'_id': username}, {'$set': {'password_hash': password_hash,
                                          'updated_at': datetime.now(timezone.utc)}},
            )
        return result.matched_count == 1

    def set_active(self, username, active):
        with timeout(3):
            result = self.store.get_collection('users').update_one(
                {'_id': username}, {'$set': {'active': active,
                                          'updated_at': datetime.now(timezone.utc)}},
            )
        return result.matched_count == 1
