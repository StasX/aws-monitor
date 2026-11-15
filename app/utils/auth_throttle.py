from datetime import datetime, timezone
from hashlib import sha256
from math import ceil
from threading import Lock

from pymongo import ReturnDocument, timeout
from pymongo.errors import DuplicateKeyError

from .mongodb import MongoDB


class AuthThrottle:
    """Atomically share failed/in-flight login budgets across workers and pods."""

    def __init__(self, uri='', database='aws_monitor', store=None):
        self.store = store if store is not None else MongoDB(uri, database)
        self.lock = Lock()
        self.collection = None

    @property
    def client(self):
        return self.store.client

    def _collection(self):
        with self.lock:
            if self.collection is None:
                collection = self.store.get_collection('auth_attempts')
                collection.create_index('expiresAt', expireAfterSeconds=0)
                self.collection = collection
            return self.collection

    def reserve(self, source, limit, window):
        # Avoid persisting raw client addresses. The database isolates releases
        # or environments; all replicas must use the same database and limits.
        key = sha256(source.encode('utf-8')).hexdigest()
        expired = {'$lte': [{'$ifNull': ['$expiresAt', datetime(1970, 1, 1, tzinfo=timezone.utc)]}, '$$NOW']}
        below_limit = {'$lt': ['$count', limit]}
        pipeline = [
            {'$set': {
                'count': {'$cond': [expired, 0, '$count']},
                'expiresAt': {'$cond': [expired, {'$add': ['$$NOW', window * 1000]}, '$expiresAt']},
            }},
            {'$set': {
                'allowed': below_limit,
                'count': {'$cond': [below_limit, {'$add': ['$count', 1]}, '$count']},
                'observedAt': '$$NOW',
            }},
        ]
        with timeout(3):
            collection = self._collection()
            try:
                document = collection.find_one_and_update(
                    {'_id': key}, pipeline, upsert=True, return_document=ReturnDocument.AFTER,
                )
            except DuplicateKeyError:
                # Another pod inserted this address concurrently. The rejected
                # insert consumed no slot; retry against its existing document.
                document = collection.find_one_and_update(
                    {'_id': key}, pipeline, upsert=True, return_document=ReturnDocument.AFTER,
                )
        if document['allowed']:
            return (key, document['expiresAt']), 0
        remaining = (document['expiresAt'] - document['observedAt']).total_seconds()
        return None, max(1, ceil(remaining))

    def release(self, token):
        key, expires = token
        with timeout(3):
            # Match the window so a late success cannot refund a newer window.
            # Keep zero-count documents until TTL cleanup to avoid delete races.
            self._collection().update_one(
                {'_id': key, 'expiresAt': expires, 'count': {'$gt': 0}},
                {'$inc': {'count': -1}},
            )
