from threading import Lock

from pymongo import MongoClient
from pymongo.errors import ConfigurationError


class MongoDB:
    """One lazy, bounded connection pool per application worker."""

    def __init__(self, uri='', database='aws_monitor'):
        self.uri = uri
        self.database = database
        self.client = None
        self.lock = Lock()

    def get_collection(self, name):
        with self.lock:
            if self.client is None:
                if not self.uri:
                    raise ConfigurationError('MONGODB_URI is required for dashboard authentication')
                self.client = MongoClient(
                    self.uri, connect=False, tz_aware=True, maxPoolSize=5,
                    serverSelectionTimeoutMS=2000, connectTimeoutMS=2000,
                    socketTimeoutMS=2000, waitQueueTimeoutMS=1000,
                    retryWrites=True, w='majority',
                )
            return self.client[self.database][name]
