class AWSRefreshDeadlineExceeded(TimeoutError):
    """The resource fetch exceeded its total execution time budget."""


class CachedDataExpiredError(Exception):
    """Previously fetched resources are too old to display."""
