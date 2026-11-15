from datetime import datetime, timezone

from werkzeug.security import check_password_hash, generate_password_hash

from ..models.user import User


# Unknown and disabled accounts still perform a password check.
_DUMMY_HASH = generate_password_hash('unused-dummy-password')


class UsersLogic:
    """User validation, password security, and account lifecycle rules."""

    def __init__(self, repository):
        self.repository = repository

    @staticmethod
    def password_hash(password):
        if not isinstance(password, str) or not 15 <= len(password) <= 1024:
            raise ValueError('Password must contain 15–1024 characters.')
        return generate_password_hash(password)

    def authenticate(self, username, password):
        try:
            User.validate_username(username)
            user = self.repository.find_by_username(username)
        except ValueError:
            check_password_hash(_DUMMY_HASH, password)
            return False
        usable = user is not None and user.active
        candidate = user.password_hash if usable else _DUMMY_HASH
        try:
            matches = check_password_hash(candidate, password)
        except (ValueError, TypeError):
            check_password_hash(_DUMMY_HASH, password)
            return False
        return usable and matches

    def create(self, username, password):
        User.validate_username(username)
        password_hash = self.password_hash(password)
        now = datetime.now(timezone.utc)
        self.repository.insert(User(username, password_hash, created_at=now, updated_at=now))

    def set_password(self, username, password):
        User.validate_username(username)
        return self.repository.set_password(username, self.password_hash(password))

    def set_active(self, username, active):
        User.validate_username(username)
        if not isinstance(active, bool):
            raise ValueError('User active status must be a boolean.')
        return self.repository.set_active(username, active)
