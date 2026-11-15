from math import isfinite
from os import environ


def env_number(name, default, *, minimum, maximum, integer=False):
    """Read a numeric setting without accepting NaN, infinity, or unsafe ranges."""
    kind = 'integer' if integer else 'finite number'
    message = f'{name} must be a {kind} between {minimum} and {maximum} (inclusive)'
    try:
        value = (int if integer else float)(environ.get(name, str(default)))
    except (TypeError, ValueError, OverflowError):
        raise ValueError(message) from None
    if (not integer and not isfinite(value)) or not minimum <= value <= maximum:
        raise ValueError(message)
    return value
