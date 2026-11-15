from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True, slots=True)
class User:
    """Dashboard account and its MongoDB document representation."""

    username: str
    password_hash: str = field(repr=False)
    active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self):
        self.validate_username(self.username)
        if not isinstance(self.password_hash, str) or not self.password_hash:
            raise ValueError('User must have a password hash.')
        if not isinstance(self.active, bool):
            raise ValueError('User active status must be a boolean.')

    @staticmethod
    def validate_username(username):
        if (not isinstance(username, str) or not 1 <= len(username) <= 128
                or username != username.strip() or not username.isprintable() or ':' in username):
            raise ValueError('Username must contain 1–128 printable characters, without colons or surrounding whitespace.')

    @classmethod
    def from_document(cls, document):
        return cls(
            username=document.get('_id'), password_hash=document.get('password_hash'),
            active=document.get('active', False), created_at=document.get('created_at'),
            updated_at=document.get('updated_at'),
        )

    def to_document(self):
        return {
            '_id': self.username, 'password_hash': self.password_hash, 'active': self.active,
            'created_at': self.created_at, 'updated_at': self.updated_at,
        }
